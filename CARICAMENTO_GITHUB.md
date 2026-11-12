# Caricamento su GitHub

Playlist: 64 canali verificati, inclusa Rai 4K a 2160p. Restano 7 richieste non verificate: vedere reports/lista-completa.md.

1. Estrarre lo ZIP sul Mac.
2. Nel repository arckadweb-bit/arckad-playlist, branch main, caricare ARCKAD_TV.m3u nella radice, sostituendo la versione precedente. Non caricare lo ZIP come playlist.
3. Per mantenere aggiornamento e verifiche, caricare anche scripts/, config/, tests/, reports/, stato.json e .github/workflows/aggiorna-playlist.yml. Sul Mac Cmd+Shift+. mostra .github. Non eliminare ARCKAD_RADIO.m3u eventualmente già presente.
4. Per il workflow consentire la scrittura in Settings → Actions → General → Workflow permissions → Read and write permissions. I flussi geolocalizzati possono richiedere un runner italiano: vedere README.md.
5. Nell’app aggiornare la playlist. URL configurato: https://raw.githubusercontent.com/arckadweb-bit/arckad-playlist/main/ARCKAD_TV.m3u

Questo pacchetto è pronto per il caricamento; non è stato pubblicato automaticamente.
