-- Migrate cola_images feature-vector columns to pgvector.
-- Safe to run now: the table currently holds no rows. If it ever contains data,
-- re-embed the corpus after changing dimensions.
--
-- IMPORTANT: the dimension below MUST match EMBEDDING_DIM in the API config and
-- the model used by the ingestion pipeline. Default 768 (Gemini text-embedding-004
-- with output_dimensionality=768). Adjust if you switch models/providers.

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE "pcr-prod".cola_images
    ALTER COLUMN image_feature_vector TYPE vector(768) USING NULL,
    ALTER COLUMN text_feature_vector  TYPE vector(768) USING NULL;

-- Approximate-nearest-neighbour indexes (cosine distance).
CREATE INDEX IF NOT EXISTS cola_images_image_vec_hnsw
    ON "pcr-prod".cola_images USING hnsw (image_feature_vector vector_cosine_ops);

CREATE INDEX IF NOT EXISTS cola_images_text_vec_hnsw
    ON "pcr-prod".cola_images USING hnsw (text_feature_vector vector_cosine_ops);
