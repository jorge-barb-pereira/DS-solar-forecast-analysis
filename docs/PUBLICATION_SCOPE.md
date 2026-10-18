# Public release scope

This repository is a newly written, self-contained educational implementation of general forecasting methods. Its source, toy generator, tests and figures were prepared for this public demonstration. There is no imported source archive, dataset, notebook output, model binary, report or source-path manifest.

All sample observations and reported metrics come from the included synthetic generator. No site information, operational identifiers, account configuration or external-service credentials are needed. Public figures are generated from the toy experiment and contain no real-world measurements. The public development date refers to this implementation, not to another codebase.

The optional, newly written Open-Meteo adapter retains calls to public weather endpoints. Users supply location settings in their own environment; no location values or internal datasets are committed. Downloaded weather stays under ignored output directories, independently of the synthetic power demonstration. Provider response metadata is filtered before export. See [provider setup and attribution](OPEN_METEO.md).

The generic methods and citations do not assert affiliation, endorsement, deployment history or performance of any external organization. This release does not establish permission to redistribute any other source or data. Future contributions must preserve the same separation and use newly authored or explicitly licensed material.
