package kube

import (
	"strings"
)

// TargetFilter holds the targeting inputs from CLI flags.
type TargetFilter struct {
	// App is a Juju application name used as a label/prefix filter.
	App string
	// Unit is a Juju unit name (e.g. "redis-k8s/0") used as a label/prefix filter.
	Unit string
	// Pod is an exact pod name.
	Pod string
}

// Empty returns true when no targeting filter is set.
func (t TargetFilter) Empty() bool {
	return t.App == "" && t.Unit == "" && t.Pod == ""
}

// MatchesPod returns true when the pod name matches the filter.
// Matching rules:
//  1. Exact pod name match (strongest signal).
//  2. Juju unit match: "app/N" → prefix "app-N-" or suffix "-N" via StatefulSet
//     naming convention.
//  3. Juju app match: pod name starts with the app name (prefix heuristic).
func (t TargetFilter) MatchesPod(podName string, labels map[string]string) bool {
	if t.Empty() {
		return true
	}

	if t.Pod != "" {
		return podName == t.Pod
	}

	if t.Unit != "" {
		// Juju unit "app/0" → pod is typically "app-0" for StatefulSets.
		normalised := strings.ReplaceAll(t.Unit, "/", "-")
		if podName == normalised {
			return true
		}
		// Also check the "app.kubernetes.io/name" label.
		if v, ok := labels["app.kubernetes.io/name"]; ok {
			parts := strings.SplitN(t.Unit, "/", 2)
			if len(parts) == 2 && v == parts[0] {
				return true
			}
		}
		return strings.HasPrefix(podName, normalised)
	}

	if t.App != "" {
		// Check label first.
		if v, ok := labels["app.kubernetes.io/name"]; ok && v == t.App {
			return true
		}
		if v, ok := labels["juju-app"]; ok && v == t.App {
			return true
		}
		return strings.HasPrefix(podName, t.App+"-") || podName == t.App
	}

	return false
}

// MatchesPVC returns true when the PVC name is likely associated with the
// filter target.  PVC names on StatefulSets typically follow the pattern
// "<volume-claim-name>-<pod-name>".
func (t TargetFilter) MatchesPVC(pvcName string) bool {
	if t.Empty() {
		return true
	}
	if t.Pod != "" {
		return strings.HasSuffix(pvcName, "-"+t.Pod) || pvcName == t.Pod
	}
	if t.Unit != "" {
		normalised := strings.ReplaceAll(t.Unit, "/", "-")
		return strings.Contains(pvcName, normalised) || strings.HasSuffix(pvcName, "-"+normalised)
	}
	if t.App != "" {
		return strings.Contains(pvcName, t.App)
	}
	return false
}
