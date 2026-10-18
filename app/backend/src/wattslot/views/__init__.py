"""Vues du plan pour le nouveau dashboard (phase 5, lot 5.1).

Des données, pas de HTML : chaque vue est un JSON typé que l'interface met en forme, et dont les
textes sont des codes avec paramètres (traduits par l'interface). Les calculs d'affichage du
dashboard de la v1 (SoC recalé sur le réel, production recalée, consommation des équipements
prévus…) y sont repris un par un, vérifiés contre la v1 d'origine (``dashboard.py``) sur
les 13 états de référence.

Les vues se lisent sur les plans gardés en base, au format de la v1 (le même contenu que celui
du dashboard copié), avec le contexte de la maison : fuseau, heures creuses, réglages de la
batterie, vitesses de la filtration.
"""
