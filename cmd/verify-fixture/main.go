// verify-fixture is an independently authored public interoperability adapter.
package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"time"
)

type target struct {
	Endpoint      string `json:"endpoint"`
	ExpectedTotal int    `json:"expectedTotal"`
}
type assertion struct {
	ID     string `json:"id"`
	Passed bool   `json:"passed"`
}
type evidence struct {
	Name      string `json:"name"`
	MediaType string `json:"mediaType"`
	Text      string `json:"text"`
}
type result struct {
	SchemaVersion          int         `json:"schemaVersion"`
	Verdict                string      `json:"verdict"`
	ObservedArtifactDigest string      `json:"observedArtifactDigest"`
	Assertions             []assertion `json:"assertions"`
	Evidence               []evidence  `json:"evidence"`
	Reason                 string      `json:"reason"`
}

func fetch(client *http.Client, endpoint string) ([]byte, error) {
	response, err := client.Get(endpoint)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("unexpected HTTP status %d", response.StatusCode)
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, 65537))
	if len(body) > 65536 {
		return nil, errors.New("response exceeds fixture limit")
	}
	return body, err
}

func verify(t target) (result, error) {
	u, err := url.Parse(t.Endpoint)
	if err != nil || u.Scheme != "http" || u.Hostname() != "127.0.0.1" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || u.Path != "" {
		return result{}, errors.New("only an explicit loopback fixture origin is permitted")
	}
	client := &http.Client{Timeout: 3 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return errors.New("redirects are not allowed") }}
	artifactBody, err := fetch(client, t.Endpoint+"/artifact")
	if err != nil {
		return result{}, err
	}
	var artifact struct {
		SHA256 string `json:"sha256"`
	}
	if err := json.Unmarshal(artifactBody, &artifact); err != nil {
		return result{}, err
	}
	if !regexp.MustCompile(`^[a-f0-9]{64}$`).MatchString(artifact.SHA256) {
		return result{}, errors.New("invalid observed artifact digest")
	}
	quoteBody, err := fetch(client, t.Endpoint+"/quote")
	if err != nil {
		return result{}, err
	}
	var quote struct {
		Quantity  int `json:"quantity"`
		UnitPrice int `json:"unit_price_cents"`
		Total     int `json:"total_cents"`
	}
	if err := json.Unmarshal(quoteBody, &quote); err != nil {
		return result{}, err
	}
	passed := quote.Quantity == 2 && quote.UnitPrice == 1250 && quote.Total == quote.Quantity*quote.UnitPrice && quote.Total == t.ExpectedTotal
	verdict := "FAIL"
	if passed {
		verdict = "PASS"
	}
	return result{1, verdict, "sha256:" + artifact.SHA256, []assertion{{"quote-total", passed}}, []evidence{{"quote", "application/json", string(quoteBody)}}, "Compare independently fetched quote total with the configured acceptance expectation"}, nil
}

func main() {
	var input struct {
		Target target `json:"target"`
	}
	if err := json.NewDecoder(io.LimitReader(os.Stdin, 65536)).Decode(&input); err != nil {
		fmt.Fprintln(os.Stderr, "invalid verifier input")
		os.Exit(1)
	}
	output, err := verify(input.Target)
	if err != nil {
		fmt.Fprintln(os.Stderr, "fixture verification error:", err)
		os.Exit(1)
	}
	if err := json.NewEncoder(os.Stdout).Encode(output); err != nil {
		os.Exit(1)
	}
}
