package main

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestVerifyReadbackAndNegativeControl(t *testing.T) {
	digest := strings.Repeat("a", 64)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/artifact":
			_, _ = w.Write([]byte(`{"sha256":"` + digest + `"}`))
		case "/quote":
			_, _ = w.Write([]byte(`{"quantity":2,"unit_price_cents":1250,"total_cents":2500}`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()
	for _, tc := range []struct {
		expected int
		verdict  string
	}{{2500, "PASS"}, {2501, "FAIL"}} {
		got, err := verify(target{server.URL, tc.expected})
		if err != nil {
			t.Fatal(err)
		}
		if got.Verdict != tc.verdict || got.ObservedArtifactDigest != "sha256:"+digest || got.Assertions[0].Passed != (tc.verdict == "PASS") {
			t.Fatalf("unexpected result: %#v", got)
		}
	}
}

func TestRejectRemoteAndUnavailableTargets(t *testing.T) {
	if _, err := verify(target{"https://example.com", 2500}); err == nil {
		t.Fatal("remote target accepted")
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "unavailable", http.StatusServiceUnavailable)
	}))
	defer server.Close()
	if _, err := verify(target{server.URL, 2500}); err == nil {
		t.Fatal("transport failure must not produce a result")
	}
}
