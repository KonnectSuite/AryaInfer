# Credits and project lineage

AryaInfer, maintained in [KonnectSuite/AryaInfer](https://github.com/KonnectSuite/AryaInfer),
is a fork of [PolyStrata](https://github.com/VecSzn/PolyStrata) by VecSzn.
PolyStrata is a fork of [the original Strata](https://github.com/Niko1221/Strata)
by Niko1221 and the Strata contributors.

We credit Niko1221 and the original Strata contributors for the original Qwen
engine, server, installer, web app and research. We credit VecSzn and the
PolyStrata contributors for the additional model engine, model integrations,
measurements and extensions inherited by this fork. Individual source notices,
third-party licenses and benchmark author attributions are preserved.
The original MIT copyright and permission notice remains in [LICENSE](LICENSE).

AryaInfer is configured for our i9-14900KF, RTX 4070 Ti SUPER 16 GB, 64 GB RAM,
Windows 11 host. We will build and benchmark changes against that setup, and
replace documentation wording with our measured findings as results become
available. The installed engine is currently upstream release 0.1.45; no custom
engine build or performance improvement is claimed.

Only measurements explicitly recorded as AryaInfer host results describe this
machine. Inherited tables and demos describe their original machines. Keep their
provenance when comparing, superseding or archiving them. Record the exact model,
build, configuration, workload and raw results for every new performance claim.

Technical identifiers such as `strata-poly`, the `polystrata.py` compatibility CLI,
upstream release/download URLs, original benchmark files and repository names
remain where changing them would break compatibility or erase attribution.
