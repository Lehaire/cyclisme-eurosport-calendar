# Calendrier TV cyclisme — France

Flux iCalendar unique pour Google Agenda avec les retransmissions cyclistes destinées à la France :

- Eurosport / HBO Max
- L'ÉquipeTV
- France Télévisions / France TV
- Novo19 (FDJ United Series)

Le calendrier est généré automatiquement à partir des programmes de Course du Jour et d'un petit jeu de données manuel pour les diffuseurs non encore couverts par cette source.

## Anti-doublons

Un événement possède un UID stable calculé à partir de :

**date + course + discipline/catégorie**

Les chaînes sont regroupées dans le même événement. Ainsi, si une course est diffusée sur Eurosport et L'Équipe, il n'y a qu'une seule entrée avec les deux diffuseurs.

Un changement d'horaire modifie l'événement existant au lieu d'en créer un nouveau.

## Flux

Une fois GitHub Pages activé, le flux sera :

`https://lehaire.github.io/cyclisme-eurosport-calendar/calendar.ics`

Le fichier `calendar.ics` est aussi disponible directement dans le dépôt.

## Mise à jour

GitHub Actions régénère le calendrier chaque jour à 06:15 UTC et à chaque modification du générateur.

> Les horaires de diffusion peuvent être modifiés par les chaînes. Le calendrier cherche à les refléter automatiquement mais une vérification auprès du diffuseur reste recommandée pour les événements importants.
