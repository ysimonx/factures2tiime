# Comment j'ai construit un robot de collecte de factures fournisseurs en une journée… avec Claude comme co-pilote

**GitHub** : [github.com/ysimonx/factures2tiime](https://github.com/ysimonx/factures2tiime)

---

## Le problème : 19 sources de factures, 0 envoi automatique

Chaque début de mois, c'était le même rituel : se connecter tour à tour à OVH, Scaleway, Infomaniak, Microsoft 365, Alan, Starlink, Qonto, Atlassian, Mistral, Anthropic, Mailjet, Free Mobile, Google Workspace… récupérer les PDF, les renommer, les transférer par email à mon comptable sur Tiime. Une corvée répétitive, chronophage, et franchement inutile pour un développeur.

La solution évidente : automatiser. La question : combien de temps ça prendrait ?

**Réponse avec Claude : une journée de travail.**

---

## Le plan établi ensemble avec Claude

Avant de taper la première ligne de code, j'ai commencé par décrire le problème à Claude dans les grandes lignes. En quelques échanges, nous avons co-construit un plan d'architecture clair :

### 1. Une abstraction provider unique

Chaque source de facture implémenterait une interface commune `InvoiceProvider` avec trois méthodes seulement :
- `is_enabled()` — le connecteur est-il configuré ?
- `list_invoices(since: date)` — quelles nouvelles factures ?
- `fetch_pdf(invoice, dest_dir)` — télécharger le PDF

Cette décision d'architecture a été immédiatement validée par Claude comme le point de départ idéal : on ajoute un nouveau fournisseur sans toucher au reste du code.

### 2. Une pipeline idempotente

Claude a insisté sur un point crucial dès le départ : **rendre le système crash-safe**. Si le processus s'interrompt en plein milieu d'une exécution, il doit reprendre exactement là où il s'était arrêté, sans doublon. La solution : une base SQLite locale avec une contrainte `UNIQUE(provider, invoice_id)`, et un champ `emailed_at` à `NULL` tant que l'email n'est pas envoyé. À chaque démarrage, les factures téléchargées mais non encore envoyées sont retentées automatiquement.

### 3. Un déclenchement mensuel automatique

APScheduler en mode `CronTrigger` : le 3 du mois à 6h00 (Europe/Paris), tout se déclenche sans intervention humaine.

### 4. La destination : Tiime par email

Plutôt que d'intégrer une API comptable complexe, Claude a suggéré d'exploiter l'adresse email dédiée de Tiime (`justif+XXXX@tiime.fr`) — Tiime traite automatiquement les pièces jointes reçues. Zéro API à intégrer côté comptabilité, zéro fragilité.

### 5. Docker pour le déploiement

Le tout encapsulé dans un conteneur Docker (`linux/arm64` pour Apple Silicon), avec un volume persistant pour la base SQLite et les PDFs, et rechargement automatique au redémarrage.

---

## Ce que nous avons construit en une journée

### 19 connecteurs fournisseurs, 4 patterns d'intégration

#### Pattern 1 : API REST classique (7 connecteurs)

Les fournisseurs les plus simples. Claude a généré les squelettes de chaque connecteur en quelques minutes, en s'adaptant aux particularités de chaque API :

- **OVH** — SDK officiel Python avec triple authentification (app key / secret / consumer key)
- **Scaleway** — Billing API v2 avec pagination et header `X-Auth-Token`
- **Infomaniak** — Bearer token simple, téléchargement PDF direct
- **Atlassian** — OAuth2 `client_credentials`, token renouvelé toutes les 60 minutes
- **Microsoft 365 (×2 tenants)** — Azure Billing REST API avec *async polling* : l'API répond 202 + header `Location`, il faut boucler jusqu'à obtenir le PDF
- **Qonto** — API v2 avec OAuth2 et refresh token à 90 jours

#### Pattern 2 : Automatisation navigateur avec Playwright (2 connecteurs)

Pour les fournisseurs sans API, Claude a choisi Playwright (Chromium headless) :

- **Free Mobile** — Login portal, navigation vers les factures, extraction des liens, téléchargement
- **Starlink** — Le plus complexe : désactivation de la détection d'automation, saisie email, attente du proof-of-work CAPTCHA (8s), mot de passe, puis… polling de la boîte Gmail pour intercepter le code OTP 6 chiffres envoyé par Starlink, extraction par regex, soumission du code. La session est mise en cache entre les runs.

#### Pattern 3 : Extraction depuis Gmail API (7 connecteurs)

Pour les fournisseurs qui envoient les factures directement par email plutôt que de les rendre disponibles via API :

- **Starlink** (version mail), **Google Workspace**, **Alan** (mutuelle), **Atlassian**, **Anthropic**, **Mistral**, **Mailjet**

Chaque connecteur filtre les emails par expéditeur et sujet, extrait le PDF en pièce jointe, et reconstitue les métadonnées (montant, devise, ID de facture) par regex sur le sujet.

L'OTP Starlink utilise d'ailleurs cette même infrastructure Gmail pour récupérer le code de double authentification en temps réel (polling toutes les 5 secondes, timeout 90s).

#### Pattern 4 : Stubs désactivés (6)

Claude a eu l'idée d'inclure des stubs pour les connecteurs futurs (Apple, YouTube…) qui retournent simplement une liste vide. La documentation est dans le code, prête à être activée.

---

## L'infrastructure OAuth2 : un générique réutilisable

Plutôt que de recoder la gestion des tokens à chaque fois, Claude a conçu un module OAuth2 générique :

- **`token_store.py`** — Persistance des access/refresh tokens dans SQLite, partagée entre tous les providers
- **`refresher.py`** — Renouvellement automatique avec une marge de sécurité de 5 minutes avant expiration
- **`setup_gmail.py` / `setup_qonto.py`** — Scripts one-shot pour l'autorisation initiale (ouvre le navigateur, écoute le callback OAuth2 sur localhost, stocke le refresh token)

---

## La livraison : Mailjet → Tiime

Chaque facture est envoyée comme un email distinct via l'API Mailjet :

```
Objet : [SCALEWAY] Facture 2025-04 — 23.40 EUR
De    : factures@mondomaine.fr
À     : justif+XXXX@tiime.fr
PJ    : scaleway_2025-04.pdf
```

Tiime reçoit, classe, et intègre automatiquement dans la comptabilité. Mon comptable n'a plus rien à faire de son côté non plus.

---

## Ce que Claude a apporté concrètement

Ce projet illustre bien comment travailler avec Claude sur du code :

**La vitesse de prototypage.** Pour chaque nouveau connecteur, je décrivais l'API cible (endpoint, auth, format de réponse) et Claude générait le squelette complet en quelques secondes — conforme au pattern `InvoiceProvider` établi dès le début. Pas de copier-coller d'un provider à l'autre, pas d'erreurs d'adaptation.

**La détection des cas tordus.** Le polling async de Microsoft 365 (réponse 202 → polling sur `Location`), la gestion du proof-of-work Starlink, l'expiration des refresh tokens Qonto à 90 jours — Claude a identifié ces pièges sans que j'aie besoin de les anticiper.

**La rigueur architecturale.** L'idempotence, le principe de crash-safety, la séparation claire entre `list_invoices` (quoi récupérer) et `fetch_pdf` (comment le récupérer) — des décisions que j'aurais peut-être prises seul, mais que Claude a posées immédiatement et clairement, sans hésitation.

**Les scripts d'outillage.** `run_now.py` pour un déclenchement manuel, `reset_state.py` pour les tests, les scripts OAuth2 — des petits outils que j'aurais eu tendance à remettre à plus tard et qui rendent le projet réellement utilisable.

**La sécurité.** Utilisateur Docker non-root, secrets uniquement en variables d'environnement, tokens jamais loggués — Claude les a intégrés naturellement, sans que j'aie besoin de les réclamer.

---

## La stack technique finale

| Composant | Techno |
|---|---|
| Runtime | Python 3.11 |
| Scheduler | APScheduler (CronTrigger) |
| Stockage | SQLite 3 |
| Email sortant | Mailjet REST API |
| Email entrant | Gmail API (OAuth2) |
| Browser automation | Playwright / Chromium |
| Conteneurisation | Docker (arm64) + docker-compose |
| Auth générique | OAuth2 avec refresh token SQLite |
| Tests | pytest + pytest-mock + responses |

---

## Le résultat

Depuis la mise en service, le 3 de chaque mois à 6h00 :

1. Le container se réveille
2. Contacte les 19 sources
3. Télécharge les nouvelles factures
4. Les envoie à Tiime avec les bons métadonnées
5. Log le résultat dans SQLite
6. Se rendort

Zéro intervention manuelle. Zéro facture oubliée. Zéro doublon (l'idempotence fait son travail). Et si un fournisseur est en panne ce mois-ci, le connecteur loggue l'erreur et continue — les autres factures partent quand même.

---

## Ce qu'on retient

Faire ce projet seul aurait probablement pris une semaine — entre la phase de réflexion architecturale, les 19 API à découvrir, la gestion OAuth2, le cas particulier Starlink, les tests, et le Docker. Avec Claude comme co-pilote, une journée a suffi.

Ce n'est pas parce que Claude a "écrit le code à ma place". C'est parce que nous avons travaillé comme deux développeurs : l'un pose les questions structurantes, l'autre génère les implémentations, et ensemble on valide, on ajuste, on passe au suivant.

Le code est open source : **[github.com/ysimonx/factures2tiime](https://github.com/ysimonx/factures2tiime)**

Si vous avez des fournisseurs similaires à intégrer, les PR sont ouvertes.

---

*Article rédigé avec Claude Code — qui a aussi aidé à rédiger cet article.*
