# Playlist ARCKAD — elenco definitivo

Elenco estratto da `config/ordine_originale.txt`: 71 voci distinte, nell'ordine della prima occorrenza nel foglio. Il generatore cerca sorgenti pubbliche, decodifica un campione audio/video e pubblica solo i canali verificati, senza duplicare URL o identità EPG. La risoluzione dell'etichetta viene misurata dal flusso.

## Risultato della verifica aggiornata

Consultare `stato.json` e `reports/channels.csv`. Nella verifica aggiornata del 12 novembre 2026: 64 canali hanno superato il controllo, 55 a 720p o superiore; 7 non hanno trovato un flusso compatibile verificabile. Questi ultimi non compaiono nella M3U. Il rapporto descrive le prove e i limiti dei flussi pubblici.

## Aggiornamento su GitHub

La GitHub Action in `.github/workflows/aggiorna-playlist.yml` aggiorna le fonti ogni sei ore e su avvio manuale. Quando il progetto viene copiato nel repository, abilita `Settings → Actions → General → Workflow permissions → Read and write permissions`, quindi avvia una verifica in `Actions`.

La playlist utilizzabile nell'app rimane `ARCKAD_TV.m3u` nella radice del repository. Il suo URL raw è `https://raw.githubusercontent.com/arckadweb-bit/arckad-playlist/main/ARCKAD_TV.m3u`.

Un esito di decodifica è una prova del momento e della rete di test: non garantisce la disponibilità futura o su ogni rete. Canali protetti da DRM, sessioni temporanee o senza audio/video compatibili restano fuori.

Dettaglio dei 23 canali richiesti: `reports/aggiunta-23-canali.md`. Regione selezionata: Toscana. Aggiornamento locale, non ancora caricato su GitHub.

Ulteriore ricerca: recuperati Rai Gulp, Rai Sport, Rai Radio 2 e TGR Toscana. Elenco attuale: `reports/lista-completa.md`.

Nuova verifica mirata: Rai 4K aggiunto a 2160p. Restano 7 canali non verificati.
