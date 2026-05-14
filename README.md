# Distributed Video Processing Infrastructure

A production-style backend infrastructure project that simulates the distributed video processing pipeline behind platforms like YouTube, TikTok, Twitch, and Netflix.

## Goal

This project demonstrates backend and infrastructure engineering maturity through:

- asynchronous video processing
- distributed worker architecture
- queue-based job orchestration
- object storage
- PostgreSQL metadata persistence
- Redis/Kafka-style messaging concepts
- FFmpeg-based transcoding
- observability with metrics, logs, and dashboards
- fault tolerance, retries, and dead-letter queues
- load testing and throughput optimization
- containerization and Kubernetes deployment concepts

## High-Level Flow

1. User uploads a video
2. API stores raw video
3. API creates a processing job
4. Queue dispatches work to workers
5. Workers transcode video using FFmpeg
6. Workers generate thumbnails and metadata
7. Job progress is updated
8. Processed outputs become streamable
9. Metrics/logs track system health

## Engineering Focus

This is not a CRUD app or social media clone.  
The focus is distributed backend infrastructure, reliability, scalability, and observability.

## Development Phases

### Phase 1: Local API + synchronous FFmpeg processing
Build a clean backend that accepts uploads, stores metadata, and processes videos locally.

### Phase 2: Async queue + worker system
Separate API request handling from video processing using Redis/RQ or Celery.

### Phase 3: Distributed workers
Run multiple workers concurrently and handle retries, failures, and job state transitions.

### Phase 4: Observability
Add structured logging, Prometheus metrics, and Grafana dashboards.

### Phase 5: Object storage
Replace local storage with MinIO/S3-compatible object storage.

### Phase 6: Kubernetes + autoscaling
Containerize services and deploy with Kubernetes concepts.

### Phase 7: Load testing + fault tolerance
Simulate high upload volume, worker crashes, queue backpressure, and recovery behavior.
