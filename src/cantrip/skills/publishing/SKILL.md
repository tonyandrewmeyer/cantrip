---
name: publishing
description: Publishing charms to Charmhub (upload, release, channel management)
---

# Publishing to Charmhub

This skill covers the complete workflow for publishing a charm to Charmhub, from validation through upload and release.

## Prerequisites

Before publishing, ensure:

1. **Validation passes** — run `charm_validate` to confirm unit tests pass and the charm packs successfully
2. **README exists** — run `generate_readme` to create a README.md from charm metadata
3. **Charmhub registration** — the charm name must be registered on Charmhub (`charmcraft register <name>`)
4. **Authentication** — `charmcraft login` must have been run in the environment

## Upload Workflow

### Step 1: Generate README

```
generate_readme(path="<charm_dir>")
```

This reads `charmcraft.yaml`, `WORKLOAD.md`, and `DESIGN.md` to produce a structured README with usage, configuration, actions, and integrations sections.

### Step 2: Pack the charm

```
charmcraft_pack(path="<charm_dir>")
```

This produces a `.charm` file ready for upload.

### Step 3: Upload to Charmhub

```
charmcraft_upload(charm_file="<path_to_charm_file>", confirmed=true)
```

**Always confirm with the user before uploading.** Show them:
- The charm file being uploaded
- The target Charmhub name
- Any previous revisions

The upload returns a revision number (e.g. `Revision 42`).

### Step 4: Release to a channel

```
charmcraft_release(name="<charm_name>", revision=42, channel="latest/edge", confirmed=true)
```

**Always confirm with the user before releasing.** Show them:
- The charm name and revision
- The target channel
- What channel the revision was previously in (if any)

## Channel Strategy

Charmhub uses a track/risk channel system:

| Channel | Purpose | When to release |
|---------|---------|-----------------|
| `latest/edge` | Development builds | After upload — default starting point |
| `latest/beta` | Feature-complete builds | After basic integration testing |
| `latest/candidate` | Release candidates | After full testing, before production |
| `latest/stable` | Production releases | After candidate validation |

**Recommended workflow:**
1. Upload → release to `latest/edge`
2. Test with `juju deploy <charm> --channel latest/edge`
3. Promote to `latest/beta` after integration tests pass
4. Promote to `latest/candidate` after broader testing
5. Promote to `latest/stable` after user approval

To promote between channels, release the same revision to the next channel — no re-upload needed.

## Resource Handling

For charms with OCI image resources:

1. Upload the OCI image as a Charmhub resource
2. Note the resource revision number
3. Include resources when releasing: `resources=["oci-image:3"]`

## Versioning Best Practices

- Use meaningful commit messages — they appear in the Charmhub revision history
- Tag releases in git to match Charmhub revisions
- Document breaking changes in the README and charm description
- Keep `CHANGELOG.md` up to date for each release

## Common Issues

- **"not registered"** — run `charmcraft register <name>` first
- **"not logged in"** — run `charmcraft login`
- **"invalid charm"** — ensure `charmcraft pack` succeeds before uploading
- **Architectures** — ensure the `.charm` file supports the required architectures (check `charmcraft.yaml` bases)
