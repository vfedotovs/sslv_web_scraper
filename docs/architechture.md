### Application Architecture Document


```mermaid
sequenceDiagram
loop Daily
  AWS Lambda->>SS.LV: Scrape Raw Data
  AWS Lambda-->>AWS S3: Upload Raw Data
end
WEB Scraper-->>AWS S3: Download Raw Data
loop Daily
  TS-->>WEB Scraper: Trigger scrape task
end
WEB Scraper-->>DB: Store Data
WEB Scraper-->>Email: Send Report

```
