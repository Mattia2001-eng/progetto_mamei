FROM python:3.9-slim

WORKDIR /app

# Copia e installa dipendenze
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia tutto il codice
COPY . .

# Esponi la porta
EXPOSE 8080

# Variabile d'ambiente per la porta
ENV PORT=8080

# Avvia l'app
CMD ["python", "app/app.py"]
