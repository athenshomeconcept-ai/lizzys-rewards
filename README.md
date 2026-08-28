# Lizzy's Rewards v3 — Production-ready package

## Νέα σε αυτή την έκδοση
- PostgreSQL ή SQLite
- Docker deployment
- Render Blueprint (`render.yaml`)
- ασφαλές SECRET_KEY μέσω environment
- secure-cookie switch
- Admin/Staff credentials μέσω environment variables
- member birthday
- marketing consent field
- admin offers
- member offers screen
- CSV export
- health endpoint
- πραγματικό QR ανά μέλος

## Online deployment — Render
1. Βάλε τον φάκελο σε GitHub repository.
2. Στο Render: New > Blueprint.
3. Σύνδεσε το repository.
4. Το `render.yaml` δημιουργεί web service + PostgreSQL.
5. Δήλωσε ADMIN_PASSWORD και STAFF_PASSWORD.
6. Deploy.
7. Θα πάρεις URL της μορφής `https://...onrender.com`.
8. Μετά σύνδεσε custom domain, π.χ. `rewards.lizzyscoffee.gr`.

## Πριν μπει σε πελάτες
- άλλαξε passwords
- χρησιμοποίησε HTTPS
- πρόσθεσε Privacy Policy / όρους loyalty
- έλεγξε ακριβώς τι marketing consent θέλεις
- κράτα backups
- δοκίμασε staff flow στο πραγματικό κινητό/tablet
- ιδανικά πρόσθεσε rate limiting και CSRF protection πριν από ευρεία χρήση

## Local
pip install -r requirements.txt
python app.py
