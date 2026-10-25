package main

import (
	"context"
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"regexp"
	"strconv"
	"time"

	_ "github.com/lib/pq"
)

const shopPage = `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Order acceptance demo</title></head><body>
<h1>Order SKU-1</h1><label>Quantity <input id="qty" type="number" min="1" max="10" value="1"></label>
<output id="total" data-cents="2499">$24.99</output><button id="place" type="button">Place order</button><output id="confirmation" hidden></output>
<script>
const q=document.querySelector('#qty'),total=document.querySelector('#total'),confirmation=document.querySelector('#confirmation');
const key=new URLSearchParams(location.search).get('checkout')||crypto.randomUUID(); let last;
q.addEventListener('input',async()=>{const qty=q.value;last=qty;const r=await fetch('/api/quote?qty='+encodeURIComponent(qty));if(!r.ok)return;const d=await r.json();if(last!==qty)return;total.dataset.cents=String(d.totalCents);total.textContent='$'+(d.totalCents/100).toFixed(2);});
document.querySelector('#place').addEventListener('click',async()=>{const r=await fetch('/api/orders',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key},body:JSON.stringify({sku:'SKU-1',qty:Number(q.value)})});if(!r.ok){confirmation.textContent='Order failed';return;}const d=await r.json();confirmation.dataset.orderId=d.id;confirmation.textContent='Order '+d.id;confirmation.hidden=false;});
</script></body></html>`

func quoteTotal(qty int) (int, error) {
	if qty < 1 || qty > 10 {
		return 0, errors.New("quantity must be 1..10")
	}
	return qty*1999 + 500, nil
}

type order struct {
	ID         string `json:"id"`
	TotalCents int    `json:"totalCents"`
}
type orderStore interface {
	Place(context.Context, string, string, int) (order, error)
	Get(context.Context, string, string) (order, error)
}
type postgresOrders struct{ db *sql.DB }

// The single SKU row serializes double-submit, including requests racing before
// an order exists. The whole mutation is committed atomically with inventory.
func (s postgresOrders) Place(ctx context.Context, identity, key string, qty int) (order, error) {
	total, err := storedOrderTotal(qty)
	if err != nil {
		return order{}, err
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return order{}, err
	}
	defer tx.Rollback()
	var stock int
	if err = tx.QueryRowContext(ctx, `SELECT quantity FROM stock WHERE sku='SKU-1' FOR UPDATE`).Scan(&stock); err != nil {
		return order{}, err
	}
	var result order
	var existingQty int
	err = tx.QueryRowContext(ctx, `SELECT id,total_cents,qty FROM orders WHERE identity=$1 AND checkout_key=$2`, identity, key).Scan(&result.ID, &result.TotalCents, &existingQty)
	if err == nil {
		if existingQty != qty {
			return order{}, errors.New("idempotency payload changed")
		}
		return result, tx.Commit()
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return order{}, err
	}
	if stock < qty {
		return order{}, errors.New("insufficient stock")
	}
	var id [16]byte
	if _, err = rand.Read(id[:]); err != nil {
		return order{}, err
	}
	result = order{ID: hex.EncodeToString(id[:]), TotalCents: total}
	if _, err = tx.ExecContext(ctx, `INSERT INTO orders(id,checkout_key,identity,sku,qty,total_cents) VALUES($1,$2,$3,'SKU-1',$4,$5)`, result.ID, key, identity, qty, total); err != nil {
		return order{}, err
	}
	if _, err = tx.ExecContext(ctx, `UPDATE stock SET quantity=quantity-$1 WHERE sku='SKU-1'`, qty); err != nil {
		return order{}, err
	}
	return result, tx.Commit()
}
func (s postgresOrders) Get(ctx context.Context, identity, id string) (order, error) {
	var result order
	err := s.db.QueryRowContext(ctx, `SELECT id,total_cents FROM orders WHERE id=$1 AND identity=$2`, id, identity).Scan(&result.ID, &result.TotalCents)
	return result, err
}

var fixtureKey = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`)

func orderRoutes(mux *http.ServeMux, store orderStore) {
	mux.HandleFunc("GET /shop", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = w.Write([]byte(shopPage))
	})
	mux.HandleFunc("GET /api/quote", func(w http.ResponseWriter, r *http.Request) {
		qty, _ := strconv.Atoi(r.URL.Query().Get("qty"))
		total, err := quoteTotal(qty)
		if err != nil {
			http.Error(w, "invalid quantity", 400)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]int{"totalCents": total})
	})
	mux.HandleFunc("POST /api/orders", func(w http.ResponseWriter, r *http.Request) {
		identity, key := r.Header.Get("X-Test-Identity"), r.Header.Get("Idempotency-Key")
		if !fixtureKey.MatchString(identity) || !fixtureKey.MatchString(key) {
			http.Error(w, "fixture identity and key required", 400)
			return
		}
		var input struct {
			SKU string `json:"sku"`
			Qty int    `json:"qty"`
		}
		decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1024))
		decoder.DisallowUnknownFields()
		if err := decoder.Decode(&input); err != nil || input.SKU != "SKU-1" {
			http.Error(w, "invalid order", 400)
			return
		}
		if _, err := quoteTotal(input.Qty); err != nil {
			http.Error(w, "invalid quantity", 400)
			return
		}
		if store == nil {
			http.Error(w, "database unavailable", 503)
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
		defer cancel()
		result, err := store.Place(ctx, identity, key, input.Qty)
		if err != nil {
			http.Error(w, "order not committed", 409)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(result)
	})
	mux.HandleFunc("GET /api/orders/{id}", func(w http.ResponseWriter, r *http.Request) {
		identity := r.Header.Get("X-Test-Identity")
		if !fixtureKey.MatchString(identity) || !fixtureKey.MatchString(r.PathValue("id")) {
			http.Error(w, "invalid identity", 400)
			return
		}
		if store == nil {
			http.Error(w, "database unavailable", 503)
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
		defer cancel()
		result, err := store.Get(ctx, identity, r.PathValue("id"))
		if err != nil {
			http.Error(w, "order unavailable", 404)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(result)
	})
}
