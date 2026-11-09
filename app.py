#!/usr/bin/env python3
"""Analyseur de parties d'échecs — Stockfish profondeur 19, UI façon Lichess.
Lancer : python3 app.py  -> http://localhost:8000
Prérequis : brew install stockfish && pip3 install chess
Place pieces.py (ton dict PIECE_IMGS collé tel quel) à côté de ce fichier."""
import base64, io, json, math, os, shutil, subprocess, sys, threading, time, urllib.request, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import chess, chess.engine, chess.pgn

DEPTH, MULTIPV, PORT = int(os.environ.get("DEPTH", 19)), 2, 8000
HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))  # dossier des ressources (aussi une fois empaqueté)
PING_TIMEOUT, LAST_PING = float(os.environ.get("PING_TIMEOUT", 150)), [0.0]
def find_sf():
    exe = "stockfish.exe" if os.name == "nt" else "stockfish"
    for c in (os.environ.get("STOCKFISH"), os.path.join(HERE, exe), shutil.which("stockfish"),
              "/opt/homebrew/bin/stockfish", "/usr/local/bin/stockfish", "/usr/games/stockfish"):
        if c and os.path.isfile(c): return c
    return "stockfish"
SF = find_sf()
try:
    from pieces import PIECE_IMGS
except ImportError:
    PIECE_IMGS = {}
MOVETIME = float(os.environ.get("MOVETIME", 25))  # plafond par position (s) : évite qu'une position lente bloque tout
ENG = None
STATE = {"status": "idle", "progress": 0, "detail": "", "result": None, "error": None}
VAL = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}
BOOK, BOOK_ERR = {}, ""

def win(cp):  # % de victoire Lichess (sert uniquement à la précision)
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)

ACC_K, ACC_C = 500, 0.10  # précision : échelle et pente réglées pour approcher le CAPS2 de chess.com (calibré sur UNE partie)

def accuracy(d):  # d = perte en points attendus (0-100) ; chess.com ne publie pas CAPS2, c'est une approximation
    return max(0, min(100, 103.1668 * math.exp(-ACC_C * d) - 3.1668))

def acc_loss(cp_best, cp_after, sgn):
    e = lambda cp: 1 / (1 + math.exp(-max(-1000, min(1000, sgn * cp)) / ACC_K))
    return max(0, e(cp_best) - e(cp_after)) * 100

cap = lambda cp: max(-1000, min(1000, cp))

def geo(a):  # moyenne géométrique : une gaffe pèse bien plus qu'avec une moyenne simple
    return round(math.exp(sum(math.log(max(x, 0.1)) for x in a) / len(a)), 1) if a else 0

EP_K = 272  # échelle logistique (centipions -> points attendus), celle de Lichess ; calibrée sur les NAG chess.com d'un PGN

def ep(info, color, ply=None):
    """Points attendus ≈ 1/(1+exp(-cp/K)), point de vue de `color` ; mats plafonnés à ±1000 cp.
    Plus plat que le modèle WDL de Stockfish, qui rendait les gaffes ~3x trop sévères par rapport à chess.com."""
    cp = info["score"].pov(color).score(mate_score=10000)
    return 1 / (1 + math.exp(-max(-1000, min(1000, cp)) / EP_K))

def material(b, color):
    return sum(v * (len(b.pieces(p, color)) - len(b.pieces(p, not color))) for p, v in VAL.items())

SEE_VAL = {1: 1, 2: 3, 3: 3, 4: 5, 5: 9, 6: 100}

def see_square(b, sq, depth=0):
    """Gain net (>= 0) du camp au trait en capturant sur `sq` avec la meilleure séquence d'échanges (coups légaux)."""
    caps = [m for m in b.legal_moves if m.to_square == sq and b.is_capture(m)]
    if not caps or depth > 12: return 0
    m = min(caps, key=lambda m: SEE_VAL[b.piece_type_at(m.from_square)])
    pt = b.piece_type_at(sq)
    c = b.copy(); c.push(m)
    return max(0, (SEE_VAL[pt] if pt else 1) - see_square(c, sq, depth + 1))

def sac_net(b, mv):
    """Matériel gagné par le coup moins la pire perte statique qu'il expose (<= -2 : vrai sacrifice).
    Réglé sur 100 brillants chess.com + ~1100 coups ordinaires : rappel 64 %, ~0,1 % de faux positifs.
    Les faux positifs venaient de positions déjà gagnées (ep_avant >= 0,84) : chess.com n'y accorde pas de brillant."""
    color, pt = b.turn, b.piece_type_at(mv.to_square)
    gained = SEE_VAL[pt] if pt else (1 if b.is_en_passant(mv) else 0)
    a = b.copy(); a.push(mv); worst = 0
    for sq, p in a.piece_map().items():
        if p.color == color and p.piece_type != chess.KING and a.is_attacked_by(not color, sq):
            worst = max(worst, see_square(a, sq))
    return gained - worst

def fetch(url):
    try:
        return urllib.request.urlopen(url, timeout=20).read().decode()
    except Exception:  # certificats Python macOS : on retombe sur curl (certificats système)
        return subprocess.run(["curl", "-fsSL", "--max-time", "30", url], capture_output=True, text=True, check=True).stdout

def load_book():
    global BOOK_ERR
    path = os.path.join(HERE, "book2.json")
    for p in (path, os.path.join(os.getcwd(), "book2.json"), os.path.expanduser("~/Downloads/book2.json")):
        try:
            if os.path.exists(p):
                book = json.load(open(p, encoding="utf-8"))
                if book: print(f"Livre d'ouvertures chargé : {len(book)} positions ({p})"); return book
        except Exception as e:
            print("book2.json illisible :", e)
    book = {}
    try:
        for f in "abcde":
            rows = fetch(f"https://raw.githubusercontent.com/lichess-org/chess-openings/master/{f}.tsv").splitlines()
            h = rows[0].split("\t"); ip, inm = h.index("pgn"), h.index("name")
            for r in rows[1:]:
                c, b, last = r.split("\t"), chess.Board(), None
                for tok in c[ip].split():
                    tok = tok.split(".")[-1]
                    if tok: b.push_san(tok); last = b.epd(); book.setdefault(last, "")
                if last: book[last] = c[inm]  # le nom n'est attaché qu'à la position finale de la ligne
        try: json.dump(book, open(path, "w", encoding="utf-8"))
        except OSError: pass  # dossier en lecture seule (appli empaquetée) : tant pis pour le cache
        print(f"Livre téléchargé : {len(book)} positions")
    except Exception as e:
        BOOK_ERR = str(e); print("Livre d'ouvertures indisponible :", e)
    return book

def GREAT(b, mv, out, ep_best, ep2, gap):
    """Great, réglé sur les « ! » de chess.com de 2 parties (5 sur 6 retrouvés, 1 en trop) :
    (1) le meilleur coup juste après une erreur adverse (perte >= 0,10), quand il est nettement
        meilleur que le suivant (écart >= 0,15) et que la position reste jouable ; captures admises ;
    (2) hors capture, seul coup qui garde l'avantage ou qui sauve la partie."""
    if b.legal_moves.count() < 3: return False
    prev = out[-1]["loss"] / 100 if out else 0
    if prev >= 0.10 and gap >= 0.15 and ep_best >= 0.45: return True
    if b.is_capture(mv): return False
    return (gap >= 0.25 and ep2 <= 0.6) or (ep_best >= 0.4 and ep2 <= 0.2)

def classify(loss):  # seuils officiels chess.com V2 (perte de points attendus)
    if loss <= 0.0005: return "best"
    if loss < 0.02: return "excellent"
    if loss < 0.05: return "good"
    if loss < 0.10: return "inaccuracy"
    if loss < 0.20: return "mistake"
    return "blunder"

PIECE_FR = {1: "un pion", 2: "un cavalier", 3: "un fou", 4: "une tour", 5: "une dame", 6: "le roi"}

def hanging(b, color):
    """Cases de pièces de `color` en prise : attaquées et soit non défendues, soit attaquées par une pièce de moindre valeur."""
    out = []
    for sq, p in b.piece_map().items():
        if p.color != color or p.piece_type == chess.KING: continue
        att = b.attackers(not color, sq)
        if att and (not b.attackers(color, sq) or min(VAL.get(b.piece_type_at(a), 99) for a in att) < VAL[p.piece_type]):
            out.append(sq)
    return out

def _unsafe_after(b, mv, color):
    c = b.copy(); c.push(mv)
    return mv.to_square in hanging(c, color)

def game_phase(b):  # phase de la partie (heuristique propre au programme) : coups joués puis matériel restant
    if b.fullmove_number <= 10: return "opening"
    mat = sum(VAL[p] * len(b.pieces(p, c)) for p in (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT) for c in (True, False))
    return "end" if mat <= 24 else "mid"

def trap_line(b, best):
    """Si le meilleur coup laisse une pièce en prise, cherche si la prendre perd aussitôt (mat en 1) : c'est alors un piège."""
    color, c = b.turn, b.copy()
    c.push(best)
    for sq in hanging(c, color):
        if VAL.get(c.piece_type_at(sq), 0) < 3: continue
        for cap in [m for m in c.legal_moves if m.to_square == sq and c.is_capture(m)]:
            d = c.copy(); san_cap = c.san(cap); d.push(cap)
            for m in d.legal_moves:
                e = d.copy(); san_m = d.san(m); e.push(m)
                if e.is_checkmate():
                    return f"Piège : {b.san(best)} laisse {PIECE_FR[c.piece_type_at(sq)]} en {chess.square_name(sq)}, mais {san_cap} perd aussitôt, car {san_m} est mat."
    return ""

def explain(b, mv, best, top, nxt, white, label, loss, gap, book=""):
    """Explication déterministe (faits calculés sur l'échiquier et la ligne du moteur), sans rien inventer."""
    try:
        if label == "book": return f"Coup de théorie{' : ' + book if book else ''}."
        if label == "great": return f"Seul bon coup : le deuxième meilleur coup perd {gap * 100:.0f} points de chances."
        if label == "brilliant": return "Sacrifice de matériel qui reste le meilleur coup : la position reste favorable."
        if label in ("good", "excellent", "best"): return trap_line(b, best) if best != mv or label == "best" else ""
        if label not in ("inaccuracy", "mistake", "miss", "blunder"): return ""
        a, t, m0, best_san = b.copy(), [], material(b, white), b.san(best)
        a.push(mv)
        sc, pv, ts = nxt["score"].pov(white), nxt.get("pv", []), top["score"].pov(white)
        before = hanging(b, white)
        if sc.is_mate() and sc.mate() < 0:
            t.append(f"Ce coup permet un mat en {abs(sc.mate())}.")
        elif pv:
            c = a.copy()
            for x in pv[:2]: c.push(x)
            drop, r = m0 - material(c, white), pv[0]
            if a.is_capture(r) and drop >= 2:
                victim = a.piece_type_at(r.to_square) or chess.PAWN
                t.append(f"Ton coup laisse {PIECE_FR[victim]} en {chess.square_name(r.to_square)} : {a.san(r)} te coûte {drop} points de matériel.")
            elif drop >= 2:
                t.append(f"Dans la ligne du moteur, tu perds {drop} points de matériel.")
        if ts.is_mate() and ts.mate() > 0 and not (sc.is_mate() and sc.mate() > 0):
            t.append(f"Tu avais un mat en {ts.mate()} avec {best_san}.")
        else:
            c = b.copy()
            for x in top["pv"][:3]: c.push(x)
            gain = material(c, white) - m0
            if gain >= 2: t.append(f"{best_san} gagnait du matériel (+{gain}) dans la ligne du moteur.")
            elif best.from_square in before and not _unsafe_after(b, best, white):
                t.append(f"{best_san} mettait en sécurité ta pièce attaquée.")
            elif b.gives_check(best): t.append(f"{best_san} donnait échec et gardait l'initiative.")
        trap = trap_line(b, best)
        if trap: t.insert(0, trap)
        if not t: t.append(f"Le moteur préférait {best_san} : ton coup perd {loss * 100:.0f} points de chances.")
        return " ".join(t[:2])
    except Exception:
        return ""

def split_phases(entries):
    """entries : (n° de coup, perte, criticité). Ouverture = 10 premiers coups ; parmi les autres, les coups tactiques
    sont les positions critiques (au moins 3 par joueur), la stratégie le reste. Aucune catégorie n'est laissée vide."""
    op = [l for f, l, c in entries if f <= 10]
    mid = sorted([(c, l) for f, l, c in entries if f > 10], reverse=True) or sorted([(c, l) for f, l, c in entries], reverse=True)
    k = max(min(3, len(mid)), sum(1 for c, l in mid if c >= 0.05))
    if len(mid) > 1: k = min(k, len(mid) - 1)
    tact = [l for c, l in mid[:k]]
    strat = [l for c, l in mid[k:]] or tact
    return {"open": op or [l for f, l, c in entries], "tact": tact, "strat": strat}

def phase_label(mean):  # échelle propre au programme, sur la perte moyenne en points attendus
    return "excellent" if mean < 0.015 else "good" if mean < 0.04 else "inaccuracy" if mean < 0.08 else "mistake" if mean < 0.15 else "blunder"

def analyse(pgn_text):
    global BOOK, ENG
    eng = None
    try:
        if not (os.path.isfile(SF) or shutil.which(SF)): raise FileNotFoundError("Stockfish introuvable : installe-le (brew install stockfish)")
        game = chess.pgn.read_game(io.StringIO(pgn_text))
        if game is None: raise ValueError("PGN illisible")
        if not BOOK: BOOK = load_book()
        board, moves = game.board(), list(game.mainline_moves())
        eng = ENG = chess.engine.SimpleEngine.popen_uci(SF)
        eng.configure({"Threads": max(1, (os.cpu_count() or 2) - 1), "Hash": 512})
        limit, shallow = chess.engine.Limit(depth=DEPTH, time=MOVETIME), 0
        infos, fens, boards = [], [], []
        for i in range(len(moves) + 1):
            fens.append(board.fen()); boards.append(board.copy())
            STATE["detail"] = f"position {i + 1}/{len(moves) + 1}"; print(STATE["detail"], flush=True)
            infos.append(eng.analyse(board, limit, multipv=MULTIPV))
            if infos[-1][0].get("depth", DEPTH) < DEPTH and "pv" in infos[-1][0]: shallow += 1
            if i < len(moves): board.push(moves[i])
            STATE["progress"] = round(100 * (i + 1) / (len(moves) + 1))
        eng.quit(); eng = None
        depths = [i_[0].get("depth", 0) for i_ in infos if "pv" in i_[0]]

        cpw = lambda info: info["score"].white().score(mate_score=10000)
        out, accs, losses, opening = [], {True: [], False: []}, {True: [], False: []}, ""
        ph = {True: [], False: []}
        for i, mv in enumerate(moves):
            b, white = boards[i], boards[i].turn
            top = infos[i][0]; best_mv = top["pv"][0]
            ep_best, ep_after = ep(top, white, b.ply()), ep(infos[i + 1][0], white, boards[i + 1].ply())
            is_best = mv == best_mv
            loss = 0 if is_best else max(0, ep_best - ep_after)
            ep2 = ep(infos[i][1], white, b.ply()) if len(infos[i]) > 1 else 0
            gap = ep_best - ep2 if len(infos[i]) > 1 else 0
            label = classify(loss)
            prev_loss = out[-1]["loss"] / 100 if out else 0
            epd, theory = boards[i + 1].epd(), bool(out) and out[-1]["label"] == "book" or not out
            in_book = epd in BOOK
            if BOOK.get(epd): opening = BOOK[epd]
            # théorie élargie : le livre Lichess est plus étroit que celui de chess.com ; on prolonge tant que
            # le coup précédent était de la théorie, que le coup est sain (best/excellent) et la position équilibrée
            if BOOK and (in_book or (theory and b.fullmove_number <= 10 and loss < 0.02 and 0.35 <= ep_after <= 0.65)):
                label = "book"
            elif loss <= 0.05 and ep_best <= 0.90 and ep_after >= 0.45 and sac_net(b, mv) <= -2:
                label = "brilliant"
            elif label == "best" and GREAT(b, mv, out, ep_best, ep2, gap):
                label = "great"
            elif label in ("good", "inaccuracy", "mistake") and prev_loss >= 0.10 and ep_best >= 0.6:
                label = "miss"  # l'adversaire a faibli, on avait une position nettement meilleure, on ne la prend pas (≠ gaffe)
            why = explain(b, mv, best_mv, top, infos[i + 1][0], white, label, loss, gap, opening if label == "book" else "")
            ph[white].append((b.fullmove_number, loss, max(gap, prev_loss)))
            sgn = 1 if white else -1
            wl = 0 if is_best else acc_loss(cpw(top), cpw(infos[i + 1][0]), sgn)
            if label != "book": accs[white].append(accuracy(wl))
            losses[white].append(max(0, sgn * (cap(cpw(top)) - cap(cpw(infos[i + 1][0])))))  # perte >= 0 par coup, mats plafonnés à ±1000
            out.append({
                "san": b.san(mv), "uci": mv.uci(), "white": white, "num": b.fullmove_number,
                "fen_before": fens[i], "fen_after": fens[i + 1], "eval": cpw(infos[i + 1][0]),
                "label": label, "loss": round(loss * 100, 1), "ep": round(ep_after, 3), "book": opening if label == "book" else "", "why": why, "gap": round(gap, 3), "ep_best": round(ep_best, 3), "phase": game_phase(b),
                "best_san": b.san(best_mv), "best_uci": best_mv.uci(),
                "best_line": b.variation_san(top["pv"][:6]),
            })
        cand = []
        for i, m in enumerate(out):
            sc = m["loss"] / 100 if m["label"] in ("blunder", "mistake", "miss", "inaccuracy") else m["gap"] * 0.8 if m["label"] == "great" else 0.5 if m["label"] == "brilliant" else 0
            if sc: cand.append((sc, i))
        moments = sorted([{"ply": i + 1, "from": round(out[i]["ep_best"] * 100), "to": round(out[i]["ep"] * 100)} for _, i in sorted(cand, reverse=True)[:5]], key=lambda k: k["ply"])
        ds = sorted(depths)
        depth_info = {"target": DEPTH, "min": ds[0] if ds else 0, "med": ds[len(ds) // 2] if ds else 0}
        avg = lambda l: round(sum(l) / len(l), 1) if l else 0
        counts = {w: {} for w in (True, False)}
        for m in out: counts[m["white"]][m["label"]] = counts[m["white"]].get(m["label"], 0) + 1
        STATE["result"] = {
            "white": game.headers.get("White", "Blancs"), "black": game.headers.get("Black", "Noirs"), "elo": {"white": game.headers.get("WhiteElo"), "black": game.headers.get("BlackElo")},
            "opening": opening, "moments": moments, "depths": depth_info, "phases": {("white" if w else "black"): {k: ({"mean": round(sum(v) / len(v) * 100, 1), "n": len(v), "label": phase_label(sum(v) / len(v))} if v else None) for k, v in split_phases(d).items()} for w, d in ph.items()}, "shallow": shallow, "book_size": len(BOOK), "book_error": BOOK_ERR, "start": fens[0], "evals": [cpw(i[0]) for i in infos], "moves": out,
            "summary": {"white": {"acc": geo(accs[True]), "acpl": round(avg(losses[True])), "counts": counts[True]},
                        "black": {"acc": geo(accs[False]), "acpl": round(avg(losses[False])), "counts": counts[False]}},
        }
        STATE["status"] = "done"
    except Exception as e:
        STATE.update(status="error", error="Analyse annulée" if ("terminated" in str(e).lower() or "died" in str(e).lower()) else str(e))
    finally:
        if eng:
            try: eng.close()
            except Exception: pass

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, body, ctype="application/json"):
        if isinstance(body, str): body = body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path == "/": return self.send(200, page(), "text/html; charset=utf-8")
        if self.path == "/status":
            return self.send(200, json.dumps({k: STATE[k] for k in ("status", "progress", "detail", "error")}))
        if self.path == "/ping":
            LAST_PING[0] = time.time(); return self.send(200, "{}")
        if self.path == "/result": return self.send(200, json.dumps(STATE["result"]))
        if self.path.startswith("/piece/"):
            k = self.path[7:].split(".")[0]
            if k in PIECE_IMGS: return self.send(200, base64.b64decode(PIECE_IMGS[k]), "image/png")
        self.send(404, "{}")
    def do_POST(self):
        if self.path == "/cancel":
            if ENG:
                try: ENG.close()
                except Exception: pass
            return self.send(200, "{}")
        if self.path == "/analyze" and STATE["status"] != "running":
            pgn = self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8", "ignore")
            STATE.update(status="running", progress=0, result=None, error=None)
            threading.Thread(target=analyse, args=(pgn,), daemon=True).start()
            return self.send(200, "{}")
        self.send(409, "{}")

def page():
    return open(os.path.join(HERE,"index.html"),encoding="utf-8").read()

def watchdog():  # ferme le programme quand l'onglet du navigateur est fermé (plus de ping)
    while True:
        time.sleep(5)
        if LAST_PING[0] and time.time() - LAST_PING[0] > PING_TIMEOUT:
            print("Onglet fermé : arrêt."); os._exit(0)

if __name__ == "__main__":
    if not PIECE_IMGS: print("⚠ pieces.py introuvable : colle ton dict PIECE_IMGS dedans.")
    srv = None
    for port in range(PORT, PORT + 10):
        try: srv = ThreadingHTTPServer(("127.0.0.1", port), H); break
        except OSError: continue
    if srv is None: sys.exit("Aucun port libre entre 8000 et 8009")
    url = f"http://localhost:{srv.server_port}"
    print(f"Stockfish: {SF} | {url}")
    args = [a for a in sys.argv[1:] if not a.startswith("-")]  # PGN glissé sur l'application
    if args and os.path.isfile(args[0]):
        STATE.update(status="running", progress=0, result=None, error=None)
        threading.Thread(target=analyse, args=(open(args[0], encoding="utf-8", errors="ignore").read(),), daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()
    try: webbrowser.open(url)
    except Exception: pass
    srv.serve_forever()