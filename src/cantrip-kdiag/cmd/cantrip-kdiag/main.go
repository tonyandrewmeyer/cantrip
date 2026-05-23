// cantrip-kdiag: read-only Kubernetes diagnostics for Cantrip charm debugging.
//
// See design/K8S_DIAGNOSTICS_BINARY.md for the full design rationale, JSON
// output contract, exit-code table, and safety boundary.
package main

import "github.com/tonyandrewmeyer/cantrip/cantrip-kdiag/internal/cli"

func main() {
	cli.Execute()
}
