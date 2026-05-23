package collect_test

import (
	"context"
	"testing"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes/fake"

	"github.com/tonyandrewmeyer/cantrip/cantrip-kdiag/internal/collect"
	"github.com/tonyandrewmeyer/cantrip/cantrip-kdiag/internal/kube"
)

func makeStorageClass(name string) *string { return &name }

func makePVC(name, namespace, phase string) *corev1.PersistentVolumeClaim {
	sc := "standard"
	return &corev1.PersistentVolumeClaim{
		ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: namespace},
		Spec: corev1.PersistentVolumeClaimSpec{
			StorageClassName: &sc,
			AccessModes:      []corev1.PersistentVolumeAccessMode{corev1.ReadWriteOnce},
		},
		Status: corev1.PersistentVolumeClaimStatus{
			Phase: corev1.PersistentVolumeClaimPhase(phase),
			Capacity: corev1.ResourceList{
				"storage": resource.MustParse("1Gi"),
			},
		},
	}
}

func TestPVCs_ReturnsAllPVCsWithoutFilter(t *testing.T) {
	pvc1 := makePVC("data-redis-k8s-0", "dev", "Bound")
	pvc2 := makePVC("data-redis-k8s-1", "dev", "Bound")
	client := fake.NewSimpleClientset(pvc1, pvc2)

	pvcs, err := collect.PVCs(context.Background(), client, "dev", kube.TargetFilter{})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(pvcs) != 2 {
		t.Errorf("expected 2 PVCs, got %d", len(pvcs))
	}
}

func TestPVCs_FiltersByPodName(t *testing.T) {
	pvc1 := makePVC("data-redis-k8s-0", "dev", "Bound")
	pvc2 := makePVC("data-redis-k8s-1", "dev", "Bound")
	client := fake.NewSimpleClientset(pvc1, pvc2)

	filter := kube.TargetFilter{Pod: "redis-k8s-0"}
	pvcs, err := collect.PVCs(context.Background(), client, "dev", filter)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(pvcs) != 1 {
		t.Fatalf("expected 1 PVC, got %d", len(pvcs))
	}
	if pvcs[0].Name != "data-redis-k8s-0" {
		t.Errorf("expected data-redis-k8s-0, got %s", pvcs[0].Name)
	}
}

func TestPVCs_PendingPhasePreserved(t *testing.T) {
	pvc := makePVC("data-redis-k8s-0", "dev", "Pending")
	client := fake.NewSimpleClientset(pvc)

	pvcs, err := collect.PVCs(context.Background(), client, "dev", kube.TargetFilter{})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(pvcs) != 1 {
		t.Fatalf("expected 1 PVC")
	}
	if pvcs[0].Phase != "Pending" {
		t.Errorf("expected Pending, got %q", pvcs[0].Phase)
	}
}

func TestPVCs_ReturnsEmptySliceWhenNone(t *testing.T) {
	client := fake.NewSimpleClientset()

	pvcs, err := collect.PVCs(context.Background(), client, "dev", kube.TargetFilter{})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if pvcs == nil {
		t.Error("expected non-nil empty slice, got nil")
	}
}
