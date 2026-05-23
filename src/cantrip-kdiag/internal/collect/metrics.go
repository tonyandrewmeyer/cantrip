package collect

import (
	"context"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	"github.com/tonyandrewmeyer/cantrip/cantrip-kdiag/internal/kube"
	"github.com/tonyandrewmeyer/cantrip/cantrip-kdiag/internal/output"
)

// PodMetricsMap maps pod name to its CPU/memory snapshot.
type PodMetricsMap map[string]PodMetrics

// PodMetrics holds the CPU and memory usage for a pod.
type PodMetrics struct {
	CPUMillicores int64
	MemoryMiB     int64
}

// Metrics fetches pod CPU/memory metrics from the metrics API.
// Returns (nil, false, nil) when the metrics API is not available — callers
// should treat this as a normal non-error case.
// Returns (nil, false, err) on unexpected errors.
func Metrics(
	ctx context.Context,
	metricsClient kube.MetricsInterface,
	namespace string,
) (PodMetricsMap, bool, error) {
	list, err := metricsClient.ListPodMetrics(ctx, namespace, metav1.ListOptions{})
	if err != nil {
		// The metrics API is optional.  Treat any error (including
		// "not found" / "service unavailable") as "not available".
		return nil, false, nil
	}
	result := make(PodMetricsMap, len(list.Items))
	for _, pm := range list.Items {
		var cpuTotal, memTotal int64
		for _, c := range pm.Containers {
			if cpu, ok := c.Usage.Cpu().AsInt64(); ok {
				cpuTotal += cpu / 1_000_000 // nanocores → millicores
			}
			if mem, ok := c.Usage.Memory().AsInt64(); ok {
				memTotal += mem / (1024 * 1024) // bytes → MiB
			}
		}
		result[pm.Name] = PodMetrics{
			CPUMillicores: cpuTotal,
			MemoryMiB:     memTotal,
		}
	}
	return result, true, nil
}

// AnnotatePods adds metrics data to the pods slice in place.
// A nil metricsMap is safe and results in no annotations.
func AnnotatePods(pods []output.PodInfo, metricsMap PodMetricsMap) {
	for i := range pods {
		if m, ok := metricsMap[pods[i].Name]; ok {
			cpu := m.CPUMillicores
			mem := m.MemoryMiB
			pods[i].CPUMillicores = &cpu
			pods[i].MemoryMiB = &mem
		}
	}
}
