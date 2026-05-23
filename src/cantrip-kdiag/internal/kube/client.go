// Package kube handles Kubernetes client creation from kubeconfig/context.
package kube

import (
	"context"
	"fmt"
	"os"
	"path/filepath"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/tools/clientcmd"
	metricsv1beta1 "k8s.io/metrics/pkg/apis/metrics/v1beta1"
	metricsclient "k8s.io/metrics/pkg/client/clientset/versioned"
)

// ExitCodes mirrors the exit-code table in the design doc.
const (
	ExitKubeconfigMissing = 3
	ExitContextInvalid    = 4
	ExitAPIUnreachable    = 5
	ExitTargetNotFound    = 6
	ExitMetricsUnavailable = 7
	ExitInternalError     = 10
)

// ClientSet bundles the main and metrics Kubernetes clients.
type ClientSet struct {
	Core    kubernetes.Interface
	Metrics MetricsInterface
}

// MetricsInterface is a narrow interface for pod-metrics queries.
// Using an interface keeps the fake simple in tests.
type MetricsInterface interface {
	GetPodMetrics(ctx context.Context, namespace, name string) (*metricsv1beta1.PodMetrics, error)
	ListPodMetrics(ctx context.Context, namespace string, opts metav1.ListOptions) (*metricsv1beta1.PodMetricsList, error)
}

// realMetricsClient wraps the versioned metrics clientset.
type realMetricsClient struct {
	cs metricsclient.Interface
}

func (r *realMetricsClient) GetPodMetrics(ctx context.Context, namespace, name string) (*metricsv1beta1.PodMetrics, error) {
	return r.cs.MetricsV1beta1().PodMetricses(namespace).Get(ctx, name, metav1.GetOptions{})
}

func (r *realMetricsClient) ListPodMetrics(ctx context.Context, namespace string, opts metav1.ListOptions) (*metricsv1beta1.PodMetricsList, error) {
	return r.cs.MetricsV1beta1().PodMetricses(namespace).List(ctx, opts)
}

// KubeconfigPath returns the effective kubeconfig path.
// It prefers an explicit override, then $KUBECONFIG, then the default
// ~/.kube/config location.
func KubeconfigPath(override string) string {
	if override != "" {
		return override
	}
	if env := os.Getenv("KUBECONFIG"); env != "" {
		return env
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(home, ".kube", "config")
}

// LoadConfig loads a rest.Config from the given kubeconfig and context.
// Returns a descriptive error with exit-code guidance on failure.
func LoadConfig(kubeconfigPath, contextName string) (*clientcmd.ClientConfig, error) {
	if kubeconfigPath != "" {
		if _, err := os.Stat(kubeconfigPath); os.IsNotExist(err) {
			return nil, &KubeconfigError{
				Code:    ExitKubeconfigMissing,
				Message: fmt.Sprintf("kubeconfig not found: %s", kubeconfigPath),
			}
		}
	}

	loadingRules := clientcmd.NewDefaultClientConfigLoadingRules()
	if kubeconfigPath != "" {
		loadingRules.ExplicitPath = kubeconfigPath
	}

	overrides := &clientcmd.ConfigOverrides{}
	if contextName != "" {
		overrides.CurrentContext = contextName
	}

	cfg := clientcmd.NewNonInteractiveDeferredLoadingClientConfig(loadingRules, overrides)

	// Validate the context exists (cheap check before connecting).
	raw, err := cfg.RawConfig()
	if err != nil {
		return nil, &KubeconfigError{
			Code:    ExitKubeconfigMissing,
			Message: fmt.Sprintf("cannot load kubeconfig: %v", err),
		}
	}

	effectiveContext := contextName
	if effectiveContext == "" {
		effectiveContext = raw.CurrentContext
	}
	if effectiveContext != "" {
		if _, ok := raw.Contexts[effectiveContext]; !ok {
			return nil, &KubeconfigError{
				Code:    ExitContextInvalid,
				Message: fmt.Sprintf("context %q not found in kubeconfig", effectiveContext),
			}
		}
	}

	return &cfg, nil
}

// NewClientSet builds a ClientSet from the given kubeconfig and context.
// It does not test API connectivity; call ClientSet.Preflight for that.
func NewClientSet(kubeconfigPath, contextName string) (*ClientSet, error) {
	loadingRules := clientcmd.NewDefaultClientConfigLoadingRules()
	if kubeconfigPath != "" {
		if _, err := os.Stat(kubeconfigPath); os.IsNotExist(err) {
			return nil, &KubeconfigError{
				Code:    ExitKubeconfigMissing,
				Message: fmt.Sprintf("kubeconfig not found: %s", kubeconfigPath),
			}
		}
		loadingRules.ExplicitPath = kubeconfigPath
	}

	overrides := &clientcmd.ConfigOverrides{}
	if contextName != "" {
		overrides.CurrentContext = contextName
	}

	cfg := clientcmd.NewNonInteractiveDeferredLoadingClientConfig(loadingRules, overrides)

	// Validate the context exists before trying to connect.
	raw, err := cfg.RawConfig()
	if err != nil {
		return nil, &KubeconfigError{
			Code:    ExitKubeconfigMissing,
			Message: fmt.Sprintf("cannot load kubeconfig: %v", err),
		}
	}

	effectiveContext := contextName
	if effectiveContext == "" {
		effectiveContext = raw.CurrentContext
	}
	if effectiveContext != "" {
		if _, ok := raw.Contexts[effectiveContext]; !ok {
			return nil, &KubeconfigError{
				Code:    ExitContextInvalid,
				Message: fmt.Sprintf("context %q not found in kubeconfig", effectiveContext),
			}
		}
	}

	restCfg, err := cfg.ClientConfig()
	if err != nil {
		return nil, &KubeconfigError{
			Code:    ExitContextInvalid,
			Message: fmt.Sprintf("cannot build REST config: %v", err),
		}
	}

	coreClient, err := kubernetes.NewForConfig(restCfg)
	if err != nil {
		return nil, &KubeconfigError{
			Code:    ExitInternalError,
			Message: fmt.Sprintf("cannot create Kubernetes client: %v", err),
		}
	}

	metricsCs, err := metricsclient.NewForConfig(restCfg)
	if err != nil {
		return nil, &KubeconfigError{
			Code:    ExitInternalError,
			Message: fmt.Sprintf("cannot create metrics client: %v", err),
		}
	}

	return &ClientSet{
		Core:    coreClient,
		Metrics: &realMetricsClient{cs: metricsCs},
	}, nil
}

// KubeconfigError carries an exit code alongside the message so the CLI
// layer can exit with the correct code without a type switch on every call.
type KubeconfigError struct {
	Code    int
	Message string
}

func (e *KubeconfigError) Error() string { return e.Message }
