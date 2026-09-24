"""Pertinence jugée à la main, offre par offre, pour le CV du propriétaire.

182 offres de sa base, tirées au sort par source et par tranche de score, plus
le haut du premier classement et des cibles probables. Les numéros sont ceux de
la base : ils valent aussi sur le serveur, qui en est une copie.

3 cœur de cible : marchés, middle office, risques, crédit, trésorerie, gestion
  de portefeuille — accessible (junior à confirmé, langue parlée).
2 proche : contrôle de gestion / analyste financier, SI finance, corporate
  finance, banque et assurance hors cible, cible mais senior ou exigeante.
1 à la marge : comptabilité, RAF, finances publiques, conseiller financier
  commercial, postes de direction ou d'encadrement confirmé.
0 hors sujet, ou inaccessible (portugais, allemand, direction générale).
"""

ETIQUETTES = {
    # --- lot 1
    3: 3, 6: 0, 7: 1, 12: 2, 14: 0, 15: 3, 16: 3, 24: 2, 25: 3, 42: 0, 47: 1, 53: 1,
    59: 1, 62: 0, 63: 1, 64: 0, 79: 1, 80: 1, 92: 1, 116: 2, 124: 1, 126: 2, 134: 1,
    136: 1, 144: 0, 148: 1, 149: 0, 150: 1, 193: 0, 195: 0, 204: 1, 207: 0, 212: 1,
    227: 0, 229: 1, 231: 1, 238: 2, 241: 1, 246: 2, 267: 1, 295: 1, 470: 3, 501: 0,
    510: 1, 511: 2, 551: 3, 586: 2, 590: 2, 642: 2, 660: 1, 691: 0, 707: 0, 714: 3,
    718: 1, 724: 2, 735: 3, 764: 1, 785: 2, 809: 0, 871: 2, 883: 1, 888: 1, 913: 0,
    930: 3, 959: 0, 1036: 2, 1041: 2, 1119: 0, 1120: 0, 1207: 2,
    # --- lot 2
    1235: 3, 1242: 1, 1252: 1, 1360: 3, 1370: 2, 1443: 0, 1526: 0, 1528: 0, 1544: 3,
    1622: 0, 1658: 0, 1698: 0, 1719: 1, 1722: 2, 1726: 0, 1743: 0, 1859: 1, 2008: 1,
    2066: 1, 2144: 1, 2151: 1, 2233: 1, 2245: 1, 2249: 3, 2255: 3, 2256: 3, 2259: 2,
    2264: 2, 2268: 3, 2274: 3, 2282: 3, 2291: 1, 2292: 1, 2293: 0, 2294: 1, 2295: 1,
    2296: 0, 2297: 1, 2298: 0, 2299: 1, 2314: 2, 2401: 0, 2408: 0, 2483: 2, 2491: 2,
    2498: 1, 2504: 0, 2507: 1, 2537: 2, 2555: 0, 2607: 2, 2772: 0, 2780: 0, 2787: 0,
    2861: 0, 2866: 0, 3050: 0, 3078: 3, 3080: 3, 3096: 3, 3101: 2, 3123: 0, 3124: 1,
    3125: 1, 3132: 1, 3134: 1, 3137: 1, 3157: 1, 3164: 1, 3167: 0, 3179: 0, 3185: 1,
    3186: 1, 3191: 1, 3200: 1, 3211: 1, 3212: 1, 3219: 1, 3227: 1, 3232: 0, 3244: 2,
    3251: 1, 3254: 2, 3257: 0, 3263: 2, 3276: 0, 3280: 0, 3281: 2, 3286: 2, 3288: 0,
    3304: 3, 3320: 1, 3355: 1, 3360: 3, 3414: 0, 3492: 1, 3493: 1, 3545: 2, 3606: 2,
    3627: 2, 3632: 3, 3637: 2, 3664: 0, 3673: 0, 3831: 0, 3838: 1, 3841: 1, 4069: 0,
    4242: 0, 4393: 2, 4402: 1, 4475: 1,
}
