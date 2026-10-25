package main

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

type fakeOrders struct {
	identity, key string
	qty, calls    int
}

func (s *fakeOrders) Place(_ context.Context, identity, key string, qty int) (order, error) {
	s.identity, s.key, s.qty = identity, key, qty
	s.calls++
	total, err := quoteTotal(qty)
	return order{"fixture-order", total}, err
}
func (s *fakeOrders) Get(_ context.Context, identity, id string) (order, error) {
	if identity != s.identity || id != "fixture-order" {
		return order{}, errors.New("not found")
	}
	return order{id, 4498}, nil
}
func TestOrderQuote(t *testing.T) {
	for _, tc := range []struct{ qty, total int }{{1, 2499}, {2, 4498}, {10, 20490}} {
		got, err := quoteTotal(tc.qty)
		if err != nil || got != tc.total {
			t.Fatalf("qty %d: %d %v", tc.qty, got, err)
		}
	}
	for _, qty := range []int{-1, 0, 11, 10000000} {
		if _, err := quoteTotal(qty); err == nil {
			t.Fatalf("accepted quantity %d", qty)
		}
	}
}
func TestOrderHTTPContract(t *testing.T) {
	s := &fakeOrders{}
	h := handlerWithOrders(s)
	r := httptest.NewRequest("POST", "/api/orders", strings.NewReader(`{"sku":"SKU-1","qty":2}`))
	r.Header.Set("X-Test-Identity", "lease-1")
	r.Header.Set("Idempotency-Key", "checkout-1")
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	var got order
	_ = json.Unmarshal(w.Body.Bytes(), &got)
	if w.Code != 200 || got.TotalCents != 4498 || s.identity != "lease-1" || s.key != "checkout-1" || s.qty != 2 {
		t.Fatalf("response %d %s store %+v", w.Code, w.Body, s)
	}
	r = httptest.NewRequest("GET", "/api/orders/fixture-order", nil)
	r.Header.Set("X-Test-Identity", "other-lease")
	w = httptest.NewRecorder()
	h.ServeHTTP(w, r)
	if w.Code != 404 {
		t.Fatalf("cross-identity read: %d", w.Code)
	}
}
func TestOrderRejectsInvalidRequest(t *testing.T) {
	for _, tc := range []struct{ identity, key, body string }{
		{"", "key", `{"sku":"SKU-1","qty":2}`},
		{"lease", "", `{"sku":"SKU-1","qty":2}`},
		{"lease", "key", `{"sku":"other","qty":2}`},
		{"lease", "key", `{"sku":"SKU-1","qty":0}`},
		{"lease", "key", `{"sku":"SKU-1","qty":2,"totalCents":1}`},
	} {
		s := &fakeOrders{}
		r := httptest.NewRequest("POST", "/api/orders", strings.NewReader(tc.body))
		r.Header.Set("X-Test-Identity", tc.identity)
		r.Header.Set("Idempotency-Key", tc.key)
		w := httptest.NewRecorder()
		handlerWithOrders(s).ServeHTTP(w, r)
		if w.Code != 400 || s.calls != 0 {
			t.Fatalf("accepted invalid request %+v: %d", tc, w.Code)
		}
	}
}
func TestOrderUIAndNoDatabase(t *testing.T) {
	w := httptest.NewRecorder()
	handlerWithOrders(&fakeOrders{}).ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/", nil))
	for _, part := range []string{`id="qty"`, `id="total"`, `id="place"`, `id="confirmation" hidden`, `get('checkout')`, `Idempotency-Key`} {
		if !strings.Contains(w.Body.String(), part) {
			t.Errorf("missing %q", part)
		}
	}
	r := httptest.NewRequest("POST", "/api/orders", strings.NewReader(`{"sku":"SKU-1","qty":2}`))
	r.Header.Set("X-Test-Identity", "lease")
	r.Header.Set("Idempotency-Key", "key")
	w = httptest.NewRecorder()
	handler().ServeHTTP(w, r)
	if w.Code != 503 {
		t.Fatalf("missing database returned %d", w.Code)
	}
}
