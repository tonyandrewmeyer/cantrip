package collect

import (
	"context"
	"fmt"
	"strings"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"

	"github.com/tonyandrewmeyer/cantrip/cantrip-kdiag/internal/kube"
	"github.com/tonyandrewmeyer/cantrip/cantrip-kdiag/internal/output"
)

// PVCs collects PersistentVolumeClaim state from the namespace.
// When a filter is set, only PVCs whose names are associated with the target
// are included.
func PVCs(
	ctx context.Context,
	client kubernetes.Interface,
	namespace string,
	filter kube.TargetFilter,
) ([]output.PVCInfo, error) {
	list, err := client.CoreV1().PersistentVolumeClaims(namespace).List(ctx, metav1.ListOptions{})
	if err != nil {
		return nil, fmt.Errorf("listing PVCs: %w", err)
	}

	var pvcs []output.PVCInfo
	for _, pvc := range list.Items {
		if !filter.MatchesPVC(pvc.Name) {
			continue
		}
		storageClass := ""
		if pvc.Spec.StorageClassName != nil {
			storageClass = *pvc.Spec.StorageClassName
		}
		capacity := ""
		if q, ok := pvc.Status.Capacity["storage"]; ok {
			capacity = q.String()
		}
		var modes []string
		for _, m := range pvc.Spec.AccessModes {
			modes = append(modes, string(m))
		}
		pvcs = append(pvcs, output.PVCInfo{
			Name:         pvc.Name,
			Phase:        string(pvc.Status.Phase),
			StorageClass: storageClass,
			Capacity:     capacity,
			AccessModes:  strings.Join(modes, ","),
		})
	}
	if pvcs == nil {
		pvcs = []output.PVCInfo{}
	}
	return pvcs, nil
}
