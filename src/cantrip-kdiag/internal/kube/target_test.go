package kube_test

import (
	"testing"

	"github.com/tonyandrewmeyer/cantrip/cantrip-kdiag/internal/kube"
)

func TestTargetFilter_Empty(t *testing.T) {
	f := kube.TargetFilter{}
	if !f.Empty() {
		t.Error("empty filter should return true for Empty()")
	}
	f.App = "redis-k8s"
	if f.Empty() {
		t.Error("filter with App set should not be Empty")
	}
}

func TestTargetFilter_MatchesPod_ExactPod(t *testing.T) {
	f := kube.TargetFilter{Pod: "redis-k8s-0"}

	if !f.MatchesPod("redis-k8s-0", nil) {
		t.Error("exact pod name should match")
	}
	if f.MatchesPod("redis-k8s-1", nil) {
		t.Error("different pod name should not match")
	}
	if f.MatchesPod("redis-k8s", nil) {
		t.Error("prefix of pod name should not match")
	}
}

func TestTargetFilter_MatchesPod_AppPrefix(t *testing.T) {
	f := kube.TargetFilter{App: "redis-k8s"}

	if !f.MatchesPod("redis-k8s-0", nil) {
		t.Error("pod prefixed with app name should match")
	}
	if !f.MatchesPod("redis-k8s-1", nil) {
		t.Error("second pod prefixed with app name should match")
	}
	if f.MatchesPod("other-app-0", nil) {
		t.Error("pod with different prefix should not match")
	}
}

func TestTargetFilter_MatchesPod_AppLabel(t *testing.T) {
	f := kube.TargetFilter{App: "redis"}
	labels := map[string]string{"app.kubernetes.io/name": "redis"}

	if !f.MatchesPod("some-random-pod-name", labels) {
		t.Error("pod with matching app label should match even with different name")
	}
}

func TestTargetFilter_MatchesPod_JujuAppLabel(t *testing.T) {
	f := kube.TargetFilter{App: "redis-k8s"}
	labels := map[string]string{"juju-app": "redis-k8s"}

	if !f.MatchesPod("redis-k8s-0", labels) {
		t.Error("pod with matching juju-app label should match")
	}
}

func TestTargetFilter_MatchesPod_Unit(t *testing.T) {
	f := kube.TargetFilter{Unit: "redis-k8s/0"}

	// StatefulSet convention: "redis-k8s/0" → pod "redis-k8s-0".
	if !f.MatchesPod("redis-k8s-0", nil) {
		t.Error("normalised unit name should match pod")
	}
	if f.MatchesPod("redis-k8s-1", nil) {
		t.Error("different unit number should not match")
	}
}

func TestTargetFilter_MatchesPod_Empty(t *testing.T) {
	f := kube.TargetFilter{}

	if !f.MatchesPod("any-pod-name", nil) {
		t.Error("empty filter should match all pods")
	}
}

func TestTargetFilter_MatchesPVC_ExactPod(t *testing.T) {
	f := kube.TargetFilter{Pod: "redis-k8s-0"}

	if !f.MatchesPVC("data-redis-k8s-0") {
		t.Error("PVC ending with pod name should match")
	}
	if f.MatchesPVC("data-redis-k8s-1") {
		t.Error("PVC ending with different pod should not match")
	}
}

func TestTargetFilter_MatchesPVC_App(t *testing.T) {
	f := kube.TargetFilter{App: "redis-k8s"}

	if !f.MatchesPVC("data-redis-k8s-0") {
		t.Error("PVC containing app name should match")
	}
	if f.MatchesPVC("data-other-app-0") {
		t.Error("PVC not containing app name should not match")
	}
}

func TestTargetFilter_MatchesPVC_Empty(t *testing.T) {
	f := kube.TargetFilter{}

	if !f.MatchesPVC("any-pvc") {
		t.Error("empty filter should match all PVCs")
	}
}
