# Contesto

Il mio archivio fotografico é organizzato in una gerarchia di cartelle a 2 livelli: il primo livello è l'anno e il secondo è un raggruppamento tematico (eg. `2025/07 - Naxos/`). Vorrei che ogni fotografia fosse inserita in un `album` di Immich a seconda della cartella originaria della risorsa: ad esempio una fotografia con posizione in `./2025/07 - Naxos/` dovrà essere inserita in un album chiamato `Naxos`. 

# Obiettivo

Scrivi uno script Python che utilizzi la CLI e API di Immich per aggiungere ciascuna fotografia presente in Immich nel relativo album. Se l'album non esiste ancora deve essere creato in questo modo:
1 - recupera la lista di tutte le risorse (fotografie) da Immich con il relativo percorsa (posizione originale del file). Salva la lista in un file csv 
2 - itera la lista su ciascuna risorsa e genera in nome dell'album di destinazione in modo deterministico. Inseriscilo nel csv
3 - Se l'album esiste già aggiungi la foto all'album, altrimenti crea prima l'album e poi aggiungi la foto. Aggiorna il csv.

# Requisiti

1 - la funzione che genera il nome dell'album deve essere deterministica e dare sempre lo stesso risultato con file provenienti dalla stesso percorso.
    `/archive/2024/11 - Roma/2024-11-30_16.42.36-OnePlusNord25G.jpg` -> `Roma` 
    `/archive/2024/11 - Roma/2024-11-30_16.06.22-OnePlusNord25G.jpg` -> `Roma` 
    `/archive/2024/09 - Pigiatura uva/2024-09-22_16.01.45-AC2003.jpg` -> `Pigiatura dell'uva`
    `/archive/2024/Varie/2024-12-24_22.38.24-OnePlusNord25G.jpg` ->  `Varie 2024`
    `/archive/2020/Varie/2020-02-16_10.59.32-Nokia71.jpg` -> `Varie 2020`
2 - E' possibile che esistano due album con lo stesso nome (ma di anni diversi). Se esistono due cartelle (secondo livello) con lo stesso nome ma provenienti da due anni differenti, saranno creati due album distinti ma con lo stesso nome. E' fondamentale che le fotografie vengano aggiunte all'album corretto
3 - lo script deve tenere traccia dell'avanzamento di ciascuno step annotando i progressi in file csv localmente, in modo tale da poter interrompere o ricominciare l'esecuzione in tempi diversi senza dover ripetere operazioni già eseguite in precedenza.

4 - il file csv dovrà avere una struttura simile a questa: `filename`, `path`, `album_name`, `album_id`, `album_is_generated`, `photo_is_added_to_abum`.
