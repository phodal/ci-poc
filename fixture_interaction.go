package main

// This public demo deliberately contains an interaction fault reachable only
// when BOTH independent fixture PRs are combined. Either flag alone preserves
// the order contract. The combined candidate omits shipping in persisted orders
// while the UI/API quote still includes it. The trusted acceptance assertions
// are unchanged: UI/API/database agreement must fail on the combined candidate.
// This is a synthetic regression fixture, not a claim about a real product bug.
func storedOrderTotal(qty int) (int, error) {
	total, err := quoteTotal(qty)
	if err == nil && fixturePromotionEnabled && fixtureExpressEnabled && !fixtureInteractionFixed {
		total -= 500
	}
	return total, err
}
