package main

import (
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"os"
	"time"
)

const version = "demo-v1"
const page = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>CI smoke demo</title></head>
<body><h1>CI smoke demo</h1><p id="version">Loading version</p>
<button id="increment" type="button">Increment</button><output id="count">0</output>
<script>
let count = 0;
document.querySelector('#increment').addEventListener('click', () => {
 document.querySelector('#count').textContent = String(++count);
});
fetch('/version').then(r => { if (!r.ok) throw new Error('Version request failed'); return r.json(); })
 .then(data => { document.querySelector('#version').textContent = data.version; });
</script></body></html>`

func handler() http.Handler {
	return handlerWithOrders(nil)
}

func handlerWithOrders(store orderStore) http.Handler {
	mux := http.NewServeMux()
	orderRoutes(mux, store)
	mux.HandleFunc("GET /artifact", func(w http.ResponseWriter, r *http.Request) {
		digest, err := executableSHA256()
		if err != nil {
			http.Error(w, "artifact unavailable", http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]string{"sha256": digest})
	})
	mux.HandleFunc("GET /quote", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]int{"quantity": 2, "unit_price_cents": 1250, "total_cents": 2500})
	})
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
	})
	mux.HandleFunc("GET /version", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]string{"version": version})
	})
	mux.HandleFunc("GET /{$}", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		if store != nil {
			_, _ = w.Write([]byte(shopPage))
			return
		}
		_, _ = w.Write([]byte(page))
	})
	return mux
}

// Read the actual executable bytes. No supplied digest or environment value is echoed.
func executableSHA256() (string, error) {
	name, err := os.Executable()
	if err != nil {
		return "", err
	}
	f, err := os.Open(name)
	if err != nil {
		return "", err
	}
	defer f.Close()
	sum := sha256.New()
	if _, err := io.Copy(sum, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(sum.Sum(nil)), nil
}

func main() {
	var store orderStore
	if dsn := os.Getenv("DATABASE_URL"); dsn != "" {
		db, err := sql.Open("postgres", dsn)
		if err != nil {
			log.Fatal("database configuration failed")
		}
		defer db.Close()
		db.SetMaxOpenConns(4)
		store = postgresOrders{db}
	}
	addr := os.Getenv("LISTEN_ADDR")
	if addr == "" {
		addr = "127.0.0.1:8080"
	}
	server := &http.Server{Addr: addr, Handler: handlerWithOrders(store), ReadHeaderTimeout: 5 * time.Second, WriteTimeout: 10 * time.Second, IdleTimeout: 30 * time.Second}
	log.Println("demo listening on", addr)
	log.Fatal(server.ListenAndServe())
}
