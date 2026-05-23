// Package cli wires up the Cobra command tree for cantrip-kdiag.
package cli

import (
	"os"
	"time"

	"github.com/spf13/cobra"
)

// defaultTimeout is the default per-command timeout.
const defaultTimeout = 30 * time.Second

// rootFlags holds the flags shared across all commands.
type rootFlags struct {
	Kubeconfig string
	Context    string
	Format     string // "json" | "text"
	Timeout    time.Duration
}

// newRootCmd builds the root cobra command.
func newRootCmd() *cobra.Command {
	flags := &rootFlags{}

	root := &cobra.Command{
		Use:   "cantrip-kdiag",
		Short: "Read-only Kubernetes diagnostics for Cantrip charm debugging",
		Long: `cantrip-kdiag collects bounded, read-only Kubernetes diagnostics and
returns structured JSON. It is designed to give Cantrip first-class pod-layer
visibility when Juju's model view does not explain a failure.

All commands are read-only. No mutations, no exec, no port-forward.`,
		SilenceUsage: true,
	}

	root.PersistentFlags().StringVar(&flags.Kubeconfig, "kubeconfig", "", "Path to kubeconfig file (default: $KUBECONFIG or ~/.kube/config)")
	root.PersistentFlags().StringVar(&flags.Context, "context", "", "Kubernetes context name")
	root.PersistentFlags().StringVar(&flags.Format, "format", "json", "Output format: json or text")
	root.PersistentFlags().DurationVar(&flags.Timeout, "timeout", defaultTimeout, "Request timeout (e.g. 30s, 1m)")

	root.AddCommand(newSummaryCmd(flags))
	root.AddCommand(newPodCmd(flags))
	root.AddCommand(newPreflightCmd(flags))

	return root
}

// Execute is the entry point called from main.
func Execute() {
	if err := newRootCmd().Execute(); err != nil {
		os.Exit(2)
	}
}
