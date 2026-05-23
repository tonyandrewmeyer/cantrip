package collect

import (
	"context"
	"fmt"
	"sort"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"

	"github.com/tonyandrewmeyer/cantrip/cantrip-kdiag/internal/output"
)

// Events collects recent warning events from the namespace.
// It returns at most maxEvents entries, sorted by last-seen descending.
// If maxEvents is 0, all warning events are returned.
func Events(
	ctx context.Context,
	client kubernetes.Interface,
	namespace string,
	maxEvents int,
) ([]output.EventInfo, error) {
	list, err := client.CoreV1().Events(namespace).List(ctx, metav1.ListOptions{})
	if err != nil {
		return nil, fmt.Errorf("listing events: %w", err)
	}

	// Sort newest first by LastTimestamp.
	sort.Slice(list.Items, func(i, j int) bool {
		ti := list.Items[i].LastTimestamp.Time
		tj := list.Items[j].LastTimestamp.Time
		return ti.After(tj)
	})

	var events []output.EventInfo
	for _, ev := range list.Items {
		// Include all event types: filtering to "Warning" only would miss
		// useful "Normal" events like pull/schedule races.  The warnings
		// synthesis step extracts the warning-specific signal.
		lastSeen := ""
		if !ev.LastTimestamp.IsZero() {
			lastSeen = ev.LastTimestamp.UTC().Format("2006-01-02T15:04:05Z")
		}
		events = append(events, output.EventInfo{
			Name:          ev.Name,
			Reason:        ev.Reason,
			Message:       ev.Message,
			Count:         ev.Count,
			Type:          ev.Type,
			InvolvedObject: fmt.Sprintf("%s/%s", ev.InvolvedObject.Kind, ev.InvolvedObject.Name),
			LastSeen:      lastSeen,
		})
		if maxEvents > 0 && len(events) >= maxEvents {
			break
		}
	}
	if events == nil {
		events = []output.EventInfo{}
	}
	return events, nil
}
