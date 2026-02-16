-- Supabase initialization script for NTUPOOL chatbot RAG storage.
-- Run in Supabase SQL Editor.

create extension if not exists vector;
create extension if not exists pgcrypto;

create table if not exists public.pool_documents (
    id uuid primary key default gen_random_uuid(),
    content text not null,
    metadata jsonb not null default '{}'::jsonb,
    embedding vector(1536) not null,
    created_at timestamptz not null default now()
);

create index if not exists pool_documents_embedding_ivfflat_idx
on public.pool_documents
using ivfflat (embedding vector_cosine_ops)
with (lists = 100);

create index if not exists pool_documents_metadata_gin_idx
on public.pool_documents
using gin (metadata);

create or replace function public.match_documents(
    query_embedding vector(1536),
    match_count int default 3,
    filter jsonb default '{}'::jsonb
)
returns table (
    id uuid,
    content text,
    metadata jsonb,
    similarity float
)
language plpgsql
as $$
#variable_conflict use_column
begin
    return query
    select
        pool_documents.id,
        pool_documents.content,
        pool_documents.metadata,
        1 - (pool_documents.embedding <=> query_embedding) as similarity
    from public.pool_documents
    where pool_documents.metadata @> filter
    order by pool_documents.embedding <=> query_embedding
    limit match_count;
end;
$$;
