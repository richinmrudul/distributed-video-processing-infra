# Distributed Video Processing Infrastructure

## Distributed tracing (Jaeger)

- Jaeger UI: http://localhost:16686
- Services: `video-processing-api`, `video-processing-worker`
- Upload a video, then search traces by service or `video.id` in Jaeger

## Upload admission control

Uploads are rejected when the queue is too deep or worker count is too low. Defaults: `MAX_QUEUE_DEPTH_FOR_UPLOADS=50`, `MIN_AVAILABLE_WORKERS_FOR_UPLOADS=1`.

## Upload rate limiting

Upload rate limiting uses Redis and is separate from queue backpressure. Default: `10` uploads per `60` seconds per client IP; rejected uploads return HTTP `429`.
