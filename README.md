Analyse de parties d'échecs

Un petit programme qui analyse vos parties d'échecs avec Stockfish et affiche le résultat dans votre navigateur, avec une interface inspirée de Lichess / chess.com.

Tu colles ou tu déposes le fichier de ta partie (au format PGN), tu attends quelques instants, et tu obtiens :

une note pour chaque coup (meilleur coup, imprécision, erreur, gaffe…) ;
une précision pour les Blancs et pour les Noirs ;
une courbe d'évaluation de la partie ;
une explication courte pour chaque erreur ;
les moments clés de la partie ;
des exercices : retrouve le meilleur coup à la place de celui que tu as joué.

Tout tourne sur ton ordinateur : ta partie n'est envoyée nulle part.

Ce qu'il te faut
Outil	À quoi il sert	Comment l'obtenir
Python 3	Fait tourner le programme	python.org/downloads
Stockfish	Le moteur qui analyse les coups	Voir l'installation ci-dessous
python-chess	Bibliothèque Python qui comprend les règles des échecs	pip3 install chess
Un navigateur web	Pour afficher l'interface	Celui que tu as déjà
Pas besoin de connaître Python pour utiliser le programme : il suffit de copier-coller quelques commandes.
Installation pas à pas

Une commande se tape dans un terminal :

macOS : ouvre l'application Terminal (Cmd + Espace, puis tape « Terminal »).
Windows : ouvre PowerShell (touche Windows, puis tape « PowerShell »).
Linux : ouvre ton terminal habituel.
1. Vérifie que Python est installé
bash
python3 --version

Si tu vois un numéro de version (par exemple Python 3.12.1), c'est bon. Sinon, installe Python depuis python.org.

Sous Windows, la commande est souvent python au lieu de python3, et pip au lieu de pip3. Pense à cocher « Add Python to PATH » pendant l'installation.

2. Récupère le projet

Option A : avec Git

bash
git clone https://github.com/TON-PSEUDO/NOM-DU-DEPOT.git
cd NOM-DU-DEPOT

Option B : sans Git

Sur la page GitHub du projet, clique sur le bouton vert Code puis Download ZIP. Décompresse l'archive et ouvre le dossier dans ton terminal.

3. Installe Stockfish

macOS (avec Homebrew) :

bash
brew install stockfish

Linux (Debian / Ubuntu) :

bash
sudo apt install stockfish

Windows :

Télécharge Stockfish sur stockfishchess.org/download.
Décompresse l'archive.
Copie le fichier .exe à côté de app.py et renomme-le stockfish.exe.

Le programme cherche Stockfish tout seul aux emplacements habituels. Si le tien est ailleurs, voir Stockfish introuvable.

4. Installe la bibliothèque python-chess
bash
pip3 install chess
C'est fini.
Lancer le programme

Depuis le dossier du projet :

bash
python3 app.py

Ton navigateur s'ouvre automatiquement sur http://localhost:8000. Si la page ne s'ouvre pas toute seule, copie cette adresse dans ton navigateur.

Tu peux aussi lancer directement l'analyse d'une partie :

bash
python3 app.py ma_partie.pgn

Pour arrêter le programme : ferme l'onglet du navigateur (le programme s'éteint tout seul au bout de quelques minutes) ou tape Ctrl + C dans le terminal.

Utilisation
Récupérer une partie au format PGN
chess.com : ouvre une partie terminée → Partager → onglet PGN → copie le texte.
Lichess : ouvre une partie → Télécharger / Exporter → PGN.
Analyser
Dans l'application, dépose ton fichier .pgn dans la zone prévue, ou colle le texte dans la case.
Clique sur Lancer l'analyse.
Patiente pendant que la barre de progression avance. L'analyse est approfondie (profondeur 19) : elle peut prendre quelques minutes selon la longueur de la partie et la puissance de ton ordinateur.
Explore les résultats : clique sur un coup dans la liste, ou utilise les boutons de navigation sous l'échiquier.

L'interface propose plusieurs onglets : Résumé, Moments clés et Statistiques avancées.

Comprendre les notes des coups

Chaque coup reçoit une note, calculée à partir de la perte de chances de gain par rapport au meilleur coup du moteur.

Note	Ce que ça veut dire
Brillant	Un sacrifice de matériel qui reste un excellent coup
Très bon coup	Un coup difficile à trouver, nettement meilleur que les autres
Meilleur coup	Le choix numéro 1 du moteur
Excellent	Presque aussi bon que le meilleur (moins de 2 points de chances perdus)
Bon	Correct (moins de 5 points perdus)
Théorie	Un coup connu de l'ouverture
Imprécision	Petite perte (5 à 10 points)
Erreur	Vraie perte (10 à 20 points)
Occasion manquée	L'adversaire a faibli, mais tu n'en as pas profité
Gaffe	Grosse perte (20 points ou plus)

Les « points » correspondent à la baisse de tes chances de gagner, en pourcentage.

Réglages (facultatif)

Tu peux modifier le comportement du programme avec des variables d'environnement, sans toucher au code.

Variable	Valeur par défaut	Rôle
DEPTH	19	Profondeur d'analyse. Plus petit = plus rapide mais moins précis
MOVETIME	25	Temps maximum (en secondes) par position
STOCKFISH	(détection auto)	Chemin complet vers ton Stockfish
PING_TIMEOUT	150	Secondes avant l'arrêt automatique une fois l'onglet fermé

Exemple : une analyse plus rapide (profondeur 12).

macOS / Linux :

bash
DEPTH=12 python3 app.py

Windows (PowerShell) :

powershell
$env:DEPTH=12; python app.py
Contenu du dossier
Fichier	Rôle
app.py	Le programme principal : serveur local, appel à Stockfish, calcul des notes
index.html	L'interface (page web affichée dans le navigateur)
pieces.py	Les images des pièces d'échecs
book2.json	Le livre d'ouvertures (noms des ouvertures et coups de théorie)
Problèmes fréquents

« Stockfish introuvable » Stockfish n'est pas installé, ou le programme ne le trouve pas. Réinstalle-le (voir l'étape 3) ou indique son emplacement :

bash
STOCKFISH=/chemin/vers/stockfish python3 app.py

ModuleNotFoundError: No module named 'chess' Il manque la bibliothèque. Lance pip3 install chess.

command not found: python3 / pip3 (Windows) Essaie python et pip à la place.

« PGN illisible » Le texte collé n'est pas une partie valide. Vérifie que tu as copié l'intégralité du PGN (les coups, pas seulement l'en-tête).

La page ne s'ouvre pas Ouvre toi-même http://localhost:8000 dans ton navigateur. Si le port 8000 est occupé, le programme essaie les ports suivants (jusqu'à 8009) : regarde l'adresse affichée dans le terminal.

Il n'y a pas de pièces sur l'échiquier Le fichier pieces.py est absent ou n'est pas dans le même dossier que app.py.

L'analyse est trop lente Baisse la profondeur (DEPTH=14) ou le temps par position (MOVETIME=10).

Pour les curieux : comment ça marche ?
Le programme lance Stockfish et lui demande d'évaluer chaque position de la partie (les deux meilleures lignes à chaque fois).
Il compare ton coup au meilleur coup du moteur et calcule la perte de chances de gain.
Il en déduit la note du coup, la précision du joueur et une explication (matériel perdu, mat évité, meilleure alternative…).
Une petite page web locale affiche le tout. Le programme n'utilise que la bibliothèque standard de Python, plus python-chess.
Limites
La précision et les notes (Brillant, Très bon coup, Théorie…) sont des approximations inspirées de chess.com et Lichess, réglées sur un petit nombre de parties. Elles ne donneront pas toujours exactement les mêmes résultats.
Les explications sont générées automatiquement à partir de calculs : elles restent volontairement simples.
Ce projet n'est affilié ni à chess.com, ni à Lichess.
Crédits
Stockfish : le moteur d'échecs.
python-chess : lecture des PGN et règles du jeu.
lichess-org/chess-openings : les noms d'ouvertures utilisés dans book2.json.