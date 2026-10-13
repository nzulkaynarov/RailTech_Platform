# VPS CPU constraints — x86_64_v1 baseline

## The constraint

The production VPS (`vps-eskiz`, `176.101.56.141`, Eskiz hosting) runs on a `QEMU Virtual CPU version 2.5+` that exposes only the **x86_64_v1** baseline. Missing instructions:

```
cmpxchg16b  lahf_lm     popcnt
sse3        ssse3       sse4_1      sse4_2
```

Verify on the host:

```bash
ssh vps-eskiz 'lscpu | grep -E "Model name|Flags"'
# Model name: QEMU Virtual CPU version 2.5+
# Flags: fpu de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov pse36 clflush mmx fxsr sse sse2 ht syscall nx lm rep_good nopl xtopology cpuid tsc_known_freq pni cx16 x2apic hypervisor lahf_lm cpuid_fault pti
```

**Anything compiled against x86_64_v2** (the modern baseline since ~2023) **will SIGILL on boot.** This affects an increasing share of Linux binaries because glibc 2.34+ defaults to x86_64_v2 optimisations for many libraries.

## Confirmed casualties

| Software | Symptom | Workaround in repo |
|---|---|---|
| `minio/minio:latest` (2024+) | `Fatal glibc error: CPU does not support x86-64-v2` on container start, infinite restart loop | Gated behind `profiles: ["with-minio"]` in `docker-compose.prod.yml`; Django falls back to `FileSystemStorage` |
| NumPy ≥ 2.x | `RuntimeError: NumPy was built with baseline optimizations (X86_V2) but your machine doesn't support: (X86_V2)` on import | `numpy>=1.26,<2` pinned in `backend/requirements.txt` |
| Pandas (transitively pulls NumPy 2) | crashes when NumPy crashes | `pandas>=2.2,<2.3` pinned to stay compatible with NumPy 1.26 |
| Python 3.13 + NumPy 1.26.x | NumPy 1.26 has no wheels for 3.13; pip falls back to source build, slim image has no gfortran/BLAS | Base image pinned to `python:3.12-slim` in `backend/Dockerfile` |

## When installing new software

Before adding a new service or upgrading a dependency that has compiled components, check:

1. **Pinning option:** does the package have a 2023-era release with x86_64_v1-compatible wheels? Pin it.
2. **Source build option:** can it be built from source in the Docker image? If yes, add the necessary `apt-get install` to the builder stage (`gcc`, `gfortran`, `libopenblas-dev`, etc.) and use `pip install --no-binary <pkg>`.
3. **Avoid:** modern data-science Python stacks (scipy, torch, scikit-learn) — even with source build they take 10+ minutes to compile on a 2-vCPU VPS.

## When to remove the workarounds

When the VPS moves to a CPU that supports x86_64_v2 (Intel Haswell+ / AMD Excavator+, basically anything from 2013 onwards), drop all four constraints together:

- Remove the `with-minio` profile gating; restore `minio: service_healthy` in `backend.depends_on`.
- Restore `MINIO_*` env vars in the deploy workflow.
- Remove the `numpy<2` and `pandas<2.3` pins in `requirements.txt`.
- Bump `python:3.12-slim` back to the current stable (likely 3.13+).

Run a clean deploy and verify on a test push first — pinning rollback is the kind of change that benefits from a staging cycle.

## Resource budget (separate from CPU instruction-set issue)

The VPS has 2 vCPU and 3.8 GB RAM. With both `RailTech B2B` and the colocated `GradeSentinel` project, ~2.5 GB is committed. Leave ~0.5 GB headroom — especially for SPA rebuilds, where `npm run build` needs ~600 MB peak.
