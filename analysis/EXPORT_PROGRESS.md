# Export progress — media HD via vxtwitter

## Méthode qui fonctionne

La méthode fiable est l’API **vxtwitter**:

- lecture des liens depuis `analysis/brand_twitter_links.txt`
- extraction du tweet id
- appel `https://api.vxtwitter.com/Twitter/status/<id>`
- extraction robuste des médias depuis plusieurs schémas JSON (`media_extended`, `mediaURLs`, `media`, objets `tweet` imbriqués, variantes vidéo)
- pour `pbs.twimg.com`, préférence HD: `name=orig` puis fallback `4096x4096` puis `large`
- téléchargement local vers `analysis/extracted_brand_full/`
- rapport consolidé dans `analysis/extracted_brand_full_report.json`

Script implémenté: `scripts/export_brand_media_vxtwitter.py`

## Validation échantillon (déjà réussie)

Run échantillon précédent: **10/10 tweets OK, 17 fichiers**.

Fichiers de référence:
- `analysis/extracted_first10_report.json`
- `analysis/extracted_first10_photos.zip`

## Run complet (tous les liens brand)

Résultats du run complet:

- Total tweets: **447**
- Tweets OK: **444**
- Tweets failed: **3**
- Total fichiers exportés: **1159**

Tweets en échec (pas de média détecté dans la réponse API):
- `1995945199194017925`
- `2013617128088162489`
- `2013759209318342865`

## Assets release (hd-assets-v1)

Release tag: `hd-assets-v1`  
Lien release: <https://github.com/scarlettbenisen-stack/brand-repo-v2-quotilol-1000-y2024plus/releases/tag/hd-assets-v1>

Assets uploadés pour cet export complet:
- `extracted_brand_full_part01.zip`
- `extracted_brand_full_part02.zip`
- `extracted_brand_full_report.json`

Liens directs:
- <https://github.com/scarlettbenisen-stack/brand-repo-v2-quotilol-1000-y2024plus/releases/download/hd-assets-v1/extracted_brand_full_part01.zip>
- <https://github.com/scarlettbenisen-stack/brand-repo-v2-quotilol-1000-y2024plus/releases/download/hd-assets-v1/extracted_brand_full_part02.zip>
- <https://github.com/scarlettbenisen-stack/brand-repo-v2-quotilol-1000-y2024plus/releases/download/hd-assets-v1/extracted_brand_full_report.json>

## Recommandation next step (export incrémental continu)

Pour éviter de refaire un full run à chaque fois:

1. stocker un état `last_exported_tweet_id` / set des IDs déjà exportés
2. à chaque run, ne traiter que les nouveaux IDs ajoutés dans `brand_twitter_links.txt`
3. écrire un report incrémental + append d’un index global
4. uploader uniquement le delta (nouveau zip + report delta) sur la même release

=> moins de temps, moins de bande passante, et mise à jour continue plus simple.
