package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestJSONEndpoints(t *testing.T) {
	for _, tc := range []struct{ path, key, value string }{{"/healthz", "status", "ok"}, {"/version", "version", "demo-v1"}} {
		t.Run(tc.path, func(t *testing.T) {
			t.Parallel()
			w := httptest.NewRecorder()
			handler().ServeHTTP(w, httptest.NewRequest(http.MethodGet, tc.path, nil))
			if w.Code != http.StatusOK {
				t.Fatalf("status: %d", w.Code)
			}
			if got := w.Header().Get("Content-Type"); got != "application/json" {
				t.Fatalf("content type: %q", got)
			}
			var body map[string]string
			if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
				t.Fatal(err)
			}
			if len(body) != 1 || body[tc.key] != tc.value {
				t.Fatalf("body: %#v", body)
			}
		})
	}
}

func TestRouting(t *testing.T) {
	for _, tc := range []struct {
		method, path string
		status       int
	}{
		{http.MethodGet, "/", http.StatusOK},
		{http.MethodGet, "/missing", http.StatusNotFound},
		{http.MethodPost, "/healthz", http.StatusMethodNotAllowed},
		{http.MethodPost, "/version", http.StatusMethodNotAllowed},
	} {
		w := httptest.NewRecorder()
		handler().ServeHTTP(w, httptest.NewRequest(tc.method, tc.path, nil))
		if w.Code != tc.status {
			t.Errorf("%s %s: got %d, want %d", tc.method, tc.path, w.Code, tc.status)
		}
		if tc.path == "/" && !strings.Contains(w.Body.String(), `<button id="increment"`) {
			t.Error("home page missing interaction")
		}
	}
}

func TestArtifactAndQuote(t *testing.T) {
	w := httptest.NewRecorder()
	handler().ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/artifact", nil))
	var artifact map[string]string
	if err := json.Unmarshal(w.Body.Bytes(), &artifact); err != nil {
		t.Fatal(err)
	}
	want, err := executableSHA256()
	if err != nil {
		t.Fatal(err)
	}
	if w.Code != http.StatusOK || len(want) != 64 || artifact["sha256"] != want {
		t.Fatalf("artifact status=%d body=%v", w.Code, artifact)
	}
	w = httptest.NewRecorder()
	handler().ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/quote", nil))
	var quote map[string]int
	if err := json.Unmarshal(w.Body.Bytes(), &quote); err != nil {
		t.Fatal(err)
	}
	if quote["quantity"] != 2 || quote["unit_price_cents"] != 1250 || quote["total_cents"] != 2500 {
		t.Fatalf("unexpected quote: %v", quote)
	}
	if quote["quantity"]*quote["unit_price_cents"] != quote["total_cents"] {
		t.Fatal("quote total invariant failed")
	}
}
