| Variante | Idioma | Entrada | max_tokens | chrF vs es_419 | p50 / p95 / máx. (ms) | Rechazadas por los filtros | Truncadas |
|---|---|---|---|---|---|---|---|
| prod | ja | ref | free | 47.3 | 463 / 865 / 1236 | 15 / 50 {'longitud': 15} | 0 |
| prod | zh | ref | free | 48.6 | 424 / 806 / 1150 | 48 / 50 {'longitud': 48} | 0 |
| prod | ko | ref | free | 46.8 | 428 / 689 / 988 | 3 / 50 {'longitud': 3} | 0 |
| prod | ja | nopunct | prod | 46.4 | 445 / 765 / 900 | 22 / 50 {'longitud': 22} | 3 |
| prod | zh | nopunct | prod | 47.2 | 412 / 715 / 879 | 47 / 50 {'longitud': 47} | 3 |
| prod | ko | nopunct | prod | 46.2 | 421 / 697 / 953 | 4 / 50 {'longitud': 4} | 0 |
| prod | ja | ref | prod | 46.4 | 434 / 711 / 724 | 17 / 50 {'longitud': 17} | 4 |
| native | ja | ref | prod | 46.4 | 460 / 725 / 771 | 16 / 50 {'longitud': 16} | 4 |
| zero | ja | ref | prod | 46.0 | 433 / 671 / 687 | 20 / 50 {'longitud': 20} | 4 |
| prod | zh | ref | prod | 47.4 | 413 / 684 / 751 | 48 / 50 {'longitud': 48} | 3 |
| native | zh | ref | prod | 47.4 | 398 / 664 / 732 | 48 / 50 {'longitud': 48} | 3 |
| zero | zh | ref | prod | 46.9 | 404 / 679 / 728 | 47 / 50 {'longitud': 47} | 3 |
| prod | ko | ref | prod | 47.1 | 438 / 706 / 973 | 3 / 50 {'longitud': 3} | 0 |
| native | ko | ref | prod | 46.9 | 415 / 686 / 968 | 4 / 50 {'longitud': 3, 'idioma': 1} | 0 |
| zero | ko | ref | prod | 46.9 | 407 / 660 / 952 | 1 / 50 {'longitud': 1} | 0 |
| prod | ja | ASR parakeet_ja_ja@clean | prod | 45.0 | 405 / 662 / 669 | 18 / 50 {'longitud': 18} | 3 |
| prod | ja | ASR parakeet_ja_ja@music | prod | 44.4 | 402 / 662 / 676 | 19 / 50 {'longitud': 19} | 3 |
| prod | ja | ASR sensevoice_ja@clean | prod | 43.6 | 414 / 668 / 677 | 21 / 50 {'longitud': 21} | 4 |
| prod | ja | ASR reazon_ja_ja@clean | prod | 43.8 | 375 / 667 / 675 | 22 / 50 {'longitud': 22} | 4 |
| prod | zh | ASR xasr960_zh@clean | prod | 46.7 | 379 / 656 / 662 | 48 / 50 {'longitud': 48} | 4 |
| prod | zh | ASR xasr960_zh@music | prod | 46.6 | 374 / 658 / 663 | 47 / 50 {'longitud': 47} | 4 |
| prod | zh | ASR sensevoice_zh@clean | prod | 46.0 | 370 / 654 / 683 | 48 / 50 {'longitud': 48} | 4 |
| prod | ko | ASR sensevoice_ko@clean | prod | 45.1 | 404 / 628 / 946 | 3 / 50 {'longitud': 3} | 0 |
| prod | ko | ASR sensevoice_ko@music | prod | 44.9 | 386 / 641 / 1025 | 2 / 50 {'longitud': 2} | 0 |
| prod | ko | ASR nemotron35_bp1_ko@clean | prod | 42.8 | 381 / 645 / 683 | 31 / 50 {'longitud': 31} | 2 |
| prod | ko | ASR kangkyu64_ko@clean | prod | 44.3 | 381 / 641 / 686 | 35 / 50 {'longitud': 35} | 2 |

Proporción de longitud (caracteres de la traducción / caracteres del original) y tokens, variante prod con la referencia:

| Idioma | Longitud p50 / p95 / máx. | Rechazadas con el tope de 3 | Con tope 6 | Tokens de salida p50 / p95 / máx. | Tope de tokens de producción (min / mediana) |
|---|---|---|---|---|---|
| ja | 2.8 / 3.6 / 4.4 | 15 | 0 | 39 / 72 / 102 | 64 / 64 |
| zh | 3.9 / 4.6 / 5.0 | 48 | 0 | 36 / 72 / 100 | 64 / 64 |
| ko | 2.4 / 3.0 / 3.3 | 3 | 0 | 38 / 61 / 89 | 64 / 64 |
