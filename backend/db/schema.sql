\restrict dbmate

-- Dumped from database version 17.10 (Debian 17.10-1.pgdg12+1)
-- Dumped by pg_dump version 17.10 (Debian 17.10-0+deb13u1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


--
-- Name: data_blob_edges_check_height(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.data_blob_edges_check_height() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    parent_height INT;
BEGIN
    SELECT height INTO parent_height FROM data_nodes WHERE node_id = NEW.parent_node_id;
    IF parent_height IS DISTINCT FROM 0 THEN
        RAISE EXCEPTION
            'data_blob_edges parent must have height 0, got %',
            parent_height;
    END IF;
    RETURN NEW;
END;
$$;


--
-- Name: data_blob_edges_check_user_id(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.data_blob_edges_check_user_id() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    parent_user_id BIGINT;
    blob_user_id   BIGINT;
BEGIN
    SELECT user_id INTO parent_user_id FROM data_nodes WHERE node_id = NEW.parent_node_id;
    SELECT user_id INTO blob_user_id  FROM data_blobs WHERE blob_id = NEW.child_blob_id;
    IF parent_user_id IS DISTINCT FROM NEW.user_id THEN
        RAISE EXCEPTION 'data_blob_edges parent user_id mismatch with data_nodes';
    END IF;
    IF blob_user_id IS DISTINCT FROM NEW.user_id THEN
        RAISE EXCEPTION 'data_blob_edges child user_id mismatch with data_blobs';
    END IF;
    RETURN NEW;
END;
$$;


--
-- Name: data_blob_edges_invalidate_parent(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.data_blob_edges_invalidate_parent() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    target_parent_id BIGINT;
BEGIN
    target_parent_id := COALESCE(NEW.parent_node_id, OLD.parent_node_id);
    DELETE FROM data_node_weights WHERE node_id = target_parent_id;
    DELETE FROM data_node_abstracts WHERE node_id = target_parent_id;
    RETURN NULL;
END;
$$;


--
-- Name: data_blobs_delete_owning_file(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.data_blobs_delete_owning_file() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    DELETE FROM data_files WHERE file_id = OLD.file_id;
    RETURN NULL;
END;
$$;


--
-- Name: data_node_abstracts_check_user_id(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.data_node_abstracts_check_user_id() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    node_user_id BIGINT;
BEGIN
    SELECT user_id INTO node_user_id FROM data_nodes WHERE node_id = NEW.node_id;
    IF node_user_id IS DISTINCT FROM NEW.user_id THEN
        RAISE EXCEPTION 'data_node_abstracts user_id mismatch with data_nodes';
    END IF;
    RETURN NEW;
END;
$$;


--
-- Name: data_node_abstracts_invalidate_parents(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.data_node_abstracts_invalidate_parents() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    target_node_id BIGINT;
BEGIN
    target_node_id := COALESCE(NEW.node_id, OLD.node_id);
    DELETE FROM data_node_abstracts
    WHERE node_id IN (
        SELECT parent_node_id FROM data_node_edges
        WHERE child_node_id = target_node_id
    );
    RETURN NULL;
END;
$$;


--
-- Name: data_node_edges_check_height(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.data_node_edges_check_height() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    parent_height INT;
    child_height  INT;
BEGIN
    SELECT height INTO parent_height FROM data_nodes WHERE node_id = NEW.parent_node_id;
    SELECT height INTO child_height  FROM data_nodes WHERE node_id = NEW.child_node_id;
    IF parent_height IS DISTINCT FROM child_height + 1 THEN
        RAISE EXCEPTION
            'data_node_edges height mismatch: parent height %, child height %, '
            'expected parent height %',
            parent_height, child_height, child_height + 1;
    END IF;
    RETURN NEW;
END;
$$;


--
-- Name: data_node_edges_check_user_id(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.data_node_edges_check_user_id() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    parent_user_id BIGINT;
    child_user_id  BIGINT;
BEGIN
    SELECT user_id INTO parent_user_id FROM data_nodes WHERE node_id = NEW.parent_node_id;
    SELECT user_id INTO child_user_id  FROM data_nodes WHERE node_id = NEW.child_node_id;
    IF parent_user_id IS DISTINCT FROM NEW.user_id THEN
        RAISE EXCEPTION 'data_node_edges parent user_id mismatch with data_nodes';
    END IF;
    IF child_user_id IS DISTINCT FROM NEW.user_id THEN
        RAISE EXCEPTION 'data_node_edges child user_id mismatch with data_nodes';
    END IF;
    RETURN NEW;
END;
$$;


--
-- Name: data_node_edges_invalidate_parent(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.data_node_edges_invalidate_parent() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    target_parent_id BIGINT;
BEGIN
    target_parent_id := COALESCE(NEW.parent_node_id, OLD.parent_node_id);
    DELETE FROM data_node_weights WHERE node_id = target_parent_id;
    DELETE FROM data_node_abstracts WHERE node_id = target_parent_id;
    RETURN NULL;
END;
$$;


--
-- Name: data_node_weights_check_user_id(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.data_node_weights_check_user_id() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    node_user_id BIGINT;
BEGIN
    SELECT user_id INTO node_user_id FROM data_nodes WHERE node_id = NEW.node_id;
    IF node_user_id IS DISTINCT FROM NEW.user_id THEN
        RAISE EXCEPTION 'data_node_weights user_id mismatch with data_nodes';
    END IF;
    RETURN NEW;
END;
$$;


--
-- Name: data_node_weights_invalidate_parents(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.data_node_weights_invalidate_parents() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    target_node_id BIGINT;
BEGIN
    target_node_id := COALESCE(NEW.node_id, OLD.node_id);
    DELETE FROM data_node_weights
    WHERE node_id IN (
        SELECT parent_node_id FROM data_node_edges
        WHERE child_node_id = target_node_id
    );
    RETURN NULL;
END;
$$;


--
-- Name: data_nodes_check_root_unique(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.data_nodes_check_root_unique() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    root_count INT;
BEGIN
    SELECT count(*) INTO root_count
    FROM data_nodes
    WHERE user_id = NEW.user_id AND is_root = TRUE;
    IF root_count > 1 THEN
        RAISE EXCEPTION 'user % has more than one root node', NEW.user_id;
    END IF;
    RETURN NULL;
END;
$$;


--
-- Name: data_nodes_drop_if_orphan(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.data_nodes_drop_if_orphan() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    DELETE FROM data_nodes dn
    WHERE dn.node_id = OLD.parent_node_id
      AND NOT EXISTS (SELECT 1 FROM data_node_edges
                      WHERE parent_node_id = dn.node_id)
      AND NOT EXISTS (SELECT 1 FROM data_blob_edges
                      WHERE parent_node_id = dn.node_id);
    RETURN NULL;
END;
$$;


--
-- Name: prevent_any_update(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.prevent_any_update() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    RAISE EXCEPTION 'rows of this table are immutable; UPDATE is rejected';
END;
$$;


--
-- Name: prevent_created_at_change(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.prevent_created_at_change() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'created_at is immutable';
    END IF;
    RETURN NEW;
END;
$$;


--
-- Name: set_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: auth_google; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_google (
    user_id bigint NOT NULL,
    sub text NOT NULL,
    email text NOT NULL,
    refresh_token_enc bytea NOT NULL,
    scopes text[] NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: auth_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_sessions (
    id text NOT NULL,
    user_id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL
);


--
-- Name: data_blob_edges; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.data_blob_edges (
    blob_edge_id bigint NOT NULL,
    user_id bigint NOT NULL,
    parent_node_id bigint NOT NULL,
    child_blob_id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: data_blob_edges_blob_edge_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.data_blob_edges_blob_edge_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: data_blob_edges_blob_edge_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.data_blob_edges_blob_edge_id_seq OWNED BY public.data_blob_edges.blob_edge_id;


--
-- Name: data_blobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.data_blobs (
    blob_id bigint NOT NULL,
    user_id bigint NOT NULL,
    file_id bigint NOT NULL,
    file_blob_index integer NOT NULL,
    file_start integer NOT NULL,
    file_end integer NOT NULL,
    is_final_blob boolean NOT NULL,
    next_blob_id bigint,
    embedding_blob public.vector(1024) NOT NULL,
    embedding_with_file public.vector(1024) NOT NULL,
    abstract jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT data_blobs_check CHECK ((file_end > file_start)),
    CONSTRAINT data_blobs_check1 CHECK (((next_blob_id IS NULL) = is_final_blob)),
    CONSTRAINT data_blobs_file_blob_index_check CHECK ((file_blob_index >= 0)),
    CONSTRAINT data_blobs_file_start_check CHECK ((file_start >= 0))
);


--
-- Name: data_blobs_blob_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.data_blobs_blob_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: data_blobs_blob_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.data_blobs_blob_id_seq OWNED BY public.data_blobs.blob_id;


--
-- Name: data_files; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.data_files (
    file_id bigint NOT NULL,
    user_id bigint NOT NULL,
    path text NOT NULL,
    source text NOT NULL,
    type text NOT NULL,
    source_modified_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT data_files_source_check CHECK ((source = 'GDRIVE'::text)),
    CONSTRAINT data_files_type_check CHECK ((type = ANY (ARRAY['PDF'::text, 'TEXT'::text, 'OTHER'::text])))
);


--
-- Name: data_files_file_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.data_files_file_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: data_files_file_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.data_files_file_id_seq OWNED BY public.data_files.file_id;


--
-- Name: data_node_abstracts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.data_node_abstracts (
    node_abstract_id bigint NOT NULL,
    user_id bigint NOT NULL,
    node_id bigint NOT NULL,
    abstract jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: data_node_abstracts_node_abstract_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.data_node_abstracts_node_abstract_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: data_node_abstracts_node_abstract_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.data_node_abstracts_node_abstract_id_seq OWNED BY public.data_node_abstracts.node_abstract_id;


--
-- Name: data_node_edges; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.data_node_edges (
    node_edge_id bigint NOT NULL,
    user_id bigint NOT NULL,
    parent_node_id bigint NOT NULL,
    child_node_id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT data_node_edges_check CHECK ((parent_node_id <> child_node_id))
);


--
-- Name: data_node_edges_node_edge_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.data_node_edges_node_edge_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: data_node_edges_node_edge_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.data_node_edges_node_edge_id_seq OWNED BY public.data_node_edges.node_edge_id;


--
-- Name: data_node_weights; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.data_node_weights (
    node_weight_id bigint NOT NULL,
    user_id bigint NOT NULL,
    node_id bigint NOT NULL,
    centroid public.vector(1024) NOT NULL,
    blob_count integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT data_node_weights_blob_count_check CHECK ((blob_count > 0))
);


--
-- Name: data_node_weights_node_weight_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.data_node_weights_node_weight_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: data_node_weights_node_weight_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.data_node_weights_node_weight_id_seq OWNED BY public.data_node_weights.node_weight_id;


--
-- Name: data_nodes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.data_nodes (
    node_id bigint NOT NULL,
    user_id bigint NOT NULL,
    is_root boolean DEFAULT false NOT NULL,
    height integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT data_nodes_height_check CHECK ((height >= 0))
);


--
-- Name: data_nodes_node_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.data_nodes_node_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: data_nodes_node_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.data_nodes_node_id_seq OWNED BY public.data_nodes.node_id;


--
-- Name: oauth_access_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.oauth_access_tokens (
    token_hash bytea NOT NULL,
    user_id bigint NOT NULL,
    client_id text NOT NULL,
    scopes text[] NOT NULL,
    resource text,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: oauth_authorization_grants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.oauth_authorization_grants (
    code text NOT NULL,
    client_id text NOT NULL,
    user_id bigint,
    redirect_uri text NOT NULL,
    redirect_uri_explicit boolean NOT NULL,
    code_challenge text NOT NULL,
    requested_scopes text[] NOT NULL,
    resource text,
    client_state text,
    status text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT oauth_authorization_grants_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'granted'::text, 'consumed'::text]))),
    CONSTRAINT oauth_authorization_grants_user_id_status_check CHECK (((status = 'pending'::text) = (user_id IS NULL)))
);


--
-- Name: oauth_clients; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.oauth_clients (
    client_id text NOT NULL,
    client_name text NOT NULL,
    redirect_uris text[] NOT NULL,
    scopes text[] DEFAULT ARRAY[]::text[] NOT NULL,
    grant_types text[] DEFAULT ARRAY['authorization_code'::text, 'refresh_token'::text] NOT NULL,
    response_types text[] DEFAULT ARRAY['code'::text] NOT NULL,
    token_endpoint_auth_method text DEFAULT 'none'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: oauth_refresh_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.oauth_refresh_tokens (
    token_hash bytea NOT NULL,
    user_id bigint NOT NULL,
    client_id text NOT NULL,
    scopes text[] NOT NULL,
    resource text,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    version character varying NOT NULL
);


--
-- Name: user_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_settings (
    user_id bigint NOT NULL,
    models jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: user_slot_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_slot_tokens (
    user_id bigint NOT NULL,
    slot text NOT NULL,
    token_enc bytea NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT user_slot_tokens_slot_check CHECK ((slot = ANY (ARRAY['blob_llm'::text, 'node_llm_leaf'::text, 'node_llm_internal'::text, 'retrieval_llm'::text, 'extract_llm'::text, 'embedding'::text])))
);


--
-- Name: user_token_usage; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_token_usage (
    usage_id bigint NOT NULL,
    user_id bigint NOT NULL,
    operation text NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    input_tokens integer NOT NULL,
    output_tokens integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT user_token_usage_input_tokens_check CHECK ((input_tokens >= 0)),
    CONSTRAINT user_token_usage_operation_check CHECK ((operation = ANY (ARRAY['blob_extract'::text, 'blob_tag'::text, 'node_extract_leaf'::text, 'node_extract_internal'::text, 'retrieval'::text, 'extract_search_terms'::text, 'embed_blob'::text, 'embed_query'::text]))),
    CONSTRAINT user_token_usage_output_tokens_check CHECK ((output_tokens >= 0))
);


--
-- Name: user_token_usage_usage_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.user_token_usage_usage_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_token_usage_usage_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.user_token_usage_usage_id_seq OWNED BY public.user_token_usage.usage_id;


--
-- Name: user_worker_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_worker_events (
    event_id bigint NOT NULL,
    user_id bigint NOT NULL,
    code integer NOT NULL,
    source text NOT NULL,
    detail text,
    context jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT user_worker_events_code_check CHECK (((code >= 1000) AND (code <= 4999))),
    CONSTRAINT user_worker_events_source_check CHECK ((source = ANY (ARRAY['blob_extractor'::text, 'node_extractor'::text, 'tree_builder'::text])))
);


--
-- Name: user_worker_events_event_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.user_worker_events_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_worker_events_event_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.user_worker_events_event_id_seq OWNED BY public.user_worker_events.event_id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id bigint NOT NULL,
    user_name text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.users_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: data_blob_edges blob_edge_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_blob_edges ALTER COLUMN blob_edge_id SET DEFAULT nextval('public.data_blob_edges_blob_edge_id_seq'::regclass);


--
-- Name: data_blobs blob_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_blobs ALTER COLUMN blob_id SET DEFAULT nextval('public.data_blobs_blob_id_seq'::regclass);


--
-- Name: data_files file_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_files ALTER COLUMN file_id SET DEFAULT nextval('public.data_files_file_id_seq'::regclass);


--
-- Name: data_node_abstracts node_abstract_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_node_abstracts ALTER COLUMN node_abstract_id SET DEFAULT nextval('public.data_node_abstracts_node_abstract_id_seq'::regclass);


--
-- Name: data_node_edges node_edge_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_node_edges ALTER COLUMN node_edge_id SET DEFAULT nextval('public.data_node_edges_node_edge_id_seq'::regclass);


--
-- Name: data_node_weights node_weight_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_node_weights ALTER COLUMN node_weight_id SET DEFAULT nextval('public.data_node_weights_node_weight_id_seq'::regclass);


--
-- Name: data_nodes node_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_nodes ALTER COLUMN node_id SET DEFAULT nextval('public.data_nodes_node_id_seq'::regclass);


--
-- Name: user_token_usage usage_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_token_usage ALTER COLUMN usage_id SET DEFAULT nextval('public.user_token_usage_usage_id_seq'::regclass);


--
-- Name: user_worker_events event_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_worker_events ALTER COLUMN event_id SET DEFAULT nextval('public.user_worker_events_event_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: auth_google auth_google_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_google
    ADD CONSTRAINT auth_google_pkey PRIMARY KEY (user_id);


--
-- Name: auth_google auth_google_sub_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_google
    ADD CONSTRAINT auth_google_sub_key UNIQUE (sub);


--
-- Name: auth_sessions auth_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_sessions
    ADD CONSTRAINT auth_sessions_pkey PRIMARY KEY (id);


--
-- Name: data_blob_edges data_blob_edges_child_blob_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_blob_edges
    ADD CONSTRAINT data_blob_edges_child_blob_id_key UNIQUE (child_blob_id);


--
-- Name: data_blob_edges data_blob_edges_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_blob_edges
    ADD CONSTRAINT data_blob_edges_pkey PRIMARY KEY (blob_edge_id);


--
-- Name: data_blobs data_blobs_file_id_file_blob_index_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_blobs
    ADD CONSTRAINT data_blobs_file_id_file_blob_index_key UNIQUE (file_id, file_blob_index);


--
-- Name: data_blobs data_blobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_blobs
    ADD CONSTRAINT data_blobs_pkey PRIMARY KEY (blob_id);


--
-- Name: data_files data_files_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_files
    ADD CONSTRAINT data_files_pkey PRIMARY KEY (file_id);


--
-- Name: data_files data_files_user_id_source_path_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_files
    ADD CONSTRAINT data_files_user_id_source_path_key UNIQUE (user_id, source, path);


--
-- Name: data_node_abstracts data_node_abstracts_node_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_node_abstracts
    ADD CONSTRAINT data_node_abstracts_node_id_key UNIQUE (node_id);


--
-- Name: data_node_abstracts data_node_abstracts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_node_abstracts
    ADD CONSTRAINT data_node_abstracts_pkey PRIMARY KEY (node_abstract_id);


--
-- Name: data_node_edges data_node_edges_parent_node_id_child_node_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_node_edges
    ADD CONSTRAINT data_node_edges_parent_node_id_child_node_id_key UNIQUE (parent_node_id, child_node_id);


--
-- Name: data_node_edges data_node_edges_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_node_edges
    ADD CONSTRAINT data_node_edges_pkey PRIMARY KEY (node_edge_id);


--
-- Name: data_node_weights data_node_weights_node_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_node_weights
    ADD CONSTRAINT data_node_weights_node_id_key UNIQUE (node_id);


--
-- Name: data_node_weights data_node_weights_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_node_weights
    ADD CONSTRAINT data_node_weights_pkey PRIMARY KEY (node_weight_id);


--
-- Name: data_nodes data_nodes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_nodes
    ADD CONSTRAINT data_nodes_pkey PRIMARY KEY (node_id);


--
-- Name: oauth_access_tokens oauth_access_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_access_tokens
    ADD CONSTRAINT oauth_access_tokens_pkey PRIMARY KEY (token_hash);


--
-- Name: oauth_authorization_grants oauth_authorization_grants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_authorization_grants
    ADD CONSTRAINT oauth_authorization_grants_pkey PRIMARY KEY (code);


--
-- Name: oauth_clients oauth_clients_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_clients
    ADD CONSTRAINT oauth_clients_pkey PRIMARY KEY (client_id);


--
-- Name: oauth_refresh_tokens oauth_refresh_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_refresh_tokens
    ADD CONSTRAINT oauth_refresh_tokens_pkey PRIMARY KEY (token_hash);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);


--
-- Name: user_settings user_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_settings
    ADD CONSTRAINT user_settings_pkey PRIMARY KEY (user_id);


--
-- Name: user_slot_tokens user_slot_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_slot_tokens
    ADD CONSTRAINT user_slot_tokens_pkey PRIMARY KEY (user_id, slot);


--
-- Name: user_token_usage user_token_usage_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_token_usage
    ADD CONSTRAINT user_token_usage_pkey PRIMARY KEY (usage_id);


--
-- Name: user_worker_events user_worker_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_worker_events
    ADD CONSTRAINT user_worker_events_pkey PRIMARY KEY (event_id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: data_blobs_one_final_per_file; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX data_blobs_one_final_per_file ON public.data_blobs USING btree (file_id) WHERE is_final_blob;


--
-- Name: idx_auth_google_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_auth_google_email ON public.auth_google USING btree (email);


--
-- Name: idx_auth_sessions_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_auth_sessions_expires_at ON public.auth_sessions USING btree (expires_at);


--
-- Name: idx_auth_sessions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_auth_sessions_user_id ON public.auth_sessions USING btree (user_id);


--
-- Name: idx_data_blob_edges_user_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_data_blob_edges_user_parent ON public.data_blob_edges USING btree (user_id, parent_node_id);


--
-- Name: idx_data_blobs_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_data_blobs_user_id ON public.data_blobs USING btree (user_id);


--
-- Name: idx_data_node_abstracts_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_data_node_abstracts_user ON public.data_node_abstracts USING btree (user_id);


--
-- Name: idx_data_node_edges_child; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_data_node_edges_child ON public.data_node_edges USING btree (child_node_id);


--
-- Name: idx_data_node_edges_user_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_data_node_edges_user_parent ON public.data_node_edges USING btree (user_id, parent_node_id);


--
-- Name: idx_data_node_weights_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_data_node_weights_user ON public.data_node_weights USING btree (user_id);


--
-- Name: idx_data_nodes_user_height; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_data_nodes_user_height ON public.data_nodes USING btree (user_id, height);


--
-- Name: idx_data_nodes_user_root; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_data_nodes_user_root ON public.data_nodes USING btree (user_id) WHERE is_root;


--
-- Name: idx_oauth_access_tokens_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_oauth_access_tokens_expires_at ON public.oauth_access_tokens USING btree (expires_at);


--
-- Name: idx_oauth_access_tokens_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_oauth_access_tokens_user_id ON public.oauth_access_tokens USING btree (user_id);


--
-- Name: idx_oauth_authorization_grants_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_oauth_authorization_grants_expires_at ON public.oauth_authorization_grants USING btree (expires_at);


--
-- Name: idx_oauth_refresh_tokens_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_oauth_refresh_tokens_expires_at ON public.oauth_refresh_tokens USING btree (expires_at);


--
-- Name: idx_oauth_refresh_tokens_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_oauth_refresh_tokens_user_id ON public.oauth_refresh_tokens USING btree (user_id);


--
-- Name: idx_user_token_usage_user_id_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_token_usage_user_id_created_at ON public.user_token_usage USING btree (user_id, created_at DESC);


--
-- Name: idx_user_worker_events_user_id_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_worker_events_user_id_created_at ON public.user_worker_events USING btree (user_id, created_at DESC);


--
-- Name: auth_google auth_google_prevent_created_at_change; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER auth_google_prevent_created_at_change BEFORE UPDATE ON public.auth_google FOR EACH ROW EXECUTE FUNCTION public.prevent_created_at_change();


--
-- Name: auth_google auth_google_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER auth_google_set_updated_at BEFORE UPDATE ON public.auth_google FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: auth_sessions auth_sessions_prevent_created_at_change; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER auth_sessions_prevent_created_at_change BEFORE UPDATE ON public.auth_sessions FOR EACH ROW EXECUTE FUNCTION public.prevent_created_at_change();


--
-- Name: data_blob_edges data_blob_edges_check_height; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER data_blob_edges_check_height BEFORE INSERT ON public.data_blob_edges FOR EACH ROW EXECUTE FUNCTION public.data_blob_edges_check_height();


--
-- Name: data_blob_edges data_blob_edges_check_user_id; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER data_blob_edges_check_user_id BEFORE INSERT ON public.data_blob_edges FOR EACH ROW EXECUTE FUNCTION public.data_blob_edges_check_user_id();


--
-- Name: data_blob_edges data_blob_edges_drop_orphan_parent; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER data_blob_edges_drop_orphan_parent AFTER DELETE ON public.data_blob_edges DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.data_nodes_drop_if_orphan();


--
-- Name: data_blob_edges data_blob_edges_invalidate_parent; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER data_blob_edges_invalidate_parent AFTER INSERT OR DELETE ON public.data_blob_edges FOR EACH ROW EXECUTE FUNCTION public.data_blob_edges_invalidate_parent();


--
-- Name: data_blob_edges data_blob_edges_prevent_any_update; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER data_blob_edges_prevent_any_update BEFORE UPDATE ON public.data_blob_edges FOR EACH ROW EXECUTE FUNCTION public.prevent_any_update();


--
-- Name: data_blobs data_blobs_delete_owning_file; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER data_blobs_delete_owning_file AFTER DELETE ON public.data_blobs FOR EACH ROW EXECUTE FUNCTION public.data_blobs_delete_owning_file();


--
-- Name: data_blobs data_blobs_prevent_any_update; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER data_blobs_prevent_any_update BEFORE UPDATE ON public.data_blobs FOR EACH ROW EXECUTE FUNCTION public.prevent_any_update();


--
-- Name: data_files data_files_prevent_any_update; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER data_files_prevent_any_update BEFORE UPDATE ON public.data_files FOR EACH ROW EXECUTE FUNCTION public.prevent_any_update();


--
-- Name: data_node_abstracts data_node_abstracts_check_user_id; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER data_node_abstracts_check_user_id BEFORE INSERT ON public.data_node_abstracts FOR EACH ROW EXECUTE FUNCTION public.data_node_abstracts_check_user_id();


--
-- Name: data_node_abstracts data_node_abstracts_invalidate_parents; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER data_node_abstracts_invalidate_parents AFTER INSERT OR DELETE ON public.data_node_abstracts FOR EACH ROW EXECUTE FUNCTION public.data_node_abstracts_invalidate_parents();


--
-- Name: data_node_abstracts data_node_abstracts_prevent_any_update; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER data_node_abstracts_prevent_any_update BEFORE UPDATE ON public.data_node_abstracts FOR EACH ROW EXECUTE FUNCTION public.prevent_any_update();


--
-- Name: data_node_edges data_node_edges_check_height; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER data_node_edges_check_height BEFORE INSERT ON public.data_node_edges FOR EACH ROW EXECUTE FUNCTION public.data_node_edges_check_height();


--
-- Name: data_node_edges data_node_edges_check_user_id; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER data_node_edges_check_user_id BEFORE INSERT ON public.data_node_edges FOR EACH ROW EXECUTE FUNCTION public.data_node_edges_check_user_id();


--
-- Name: data_node_edges data_node_edges_drop_orphan_parent; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER data_node_edges_drop_orphan_parent AFTER DELETE ON public.data_node_edges DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.data_nodes_drop_if_orphan();


--
-- Name: data_node_edges data_node_edges_invalidate_parent; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER data_node_edges_invalidate_parent AFTER INSERT OR DELETE ON public.data_node_edges FOR EACH ROW EXECUTE FUNCTION public.data_node_edges_invalidate_parent();


--
-- Name: data_node_edges data_node_edges_prevent_any_update; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER data_node_edges_prevent_any_update BEFORE UPDATE ON public.data_node_edges FOR EACH ROW EXECUTE FUNCTION public.prevent_any_update();


--
-- Name: data_node_weights data_node_weights_check_user_id; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER data_node_weights_check_user_id BEFORE INSERT ON public.data_node_weights FOR EACH ROW EXECUTE FUNCTION public.data_node_weights_check_user_id();


--
-- Name: data_node_weights data_node_weights_invalidate_parents; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER data_node_weights_invalidate_parents AFTER INSERT OR DELETE ON public.data_node_weights FOR EACH ROW EXECUTE FUNCTION public.data_node_weights_invalidate_parents();


--
-- Name: data_node_weights data_node_weights_prevent_any_update; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER data_node_weights_prevent_any_update BEFORE UPDATE ON public.data_node_weights FOR EACH ROW EXECUTE FUNCTION public.prevent_any_update();


--
-- Name: data_nodes data_nodes_check_root_unique; Type: TRIGGER; Schema: public; Owner: -
--

CREATE CONSTRAINT TRIGGER data_nodes_check_root_unique AFTER INSERT ON public.data_nodes DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN ((new.is_root = true)) EXECUTE FUNCTION public.data_nodes_check_root_unique();


--
-- Name: data_nodes data_nodes_prevent_any_update; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER data_nodes_prevent_any_update BEFORE UPDATE ON public.data_nodes FOR EACH ROW EXECUTE FUNCTION public.prevent_any_update();


--
-- Name: oauth_access_tokens oauth_access_tokens_prevent_created_at_change; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER oauth_access_tokens_prevent_created_at_change BEFORE UPDATE ON public.oauth_access_tokens FOR EACH ROW EXECUTE FUNCTION public.prevent_created_at_change();


--
-- Name: oauth_authorization_grants oauth_authorization_grants_prevent_created_at_change; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER oauth_authorization_grants_prevent_created_at_change BEFORE UPDATE ON public.oauth_authorization_grants FOR EACH ROW EXECUTE FUNCTION public.prevent_created_at_change();


--
-- Name: oauth_authorization_grants oauth_authorization_grants_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER oauth_authorization_grants_set_updated_at BEFORE UPDATE ON public.oauth_authorization_grants FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: oauth_clients oauth_clients_prevent_created_at_change; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER oauth_clients_prevent_created_at_change BEFORE UPDATE ON public.oauth_clients FOR EACH ROW EXECUTE FUNCTION public.prevent_created_at_change();


--
-- Name: oauth_refresh_tokens oauth_refresh_tokens_prevent_created_at_change; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER oauth_refresh_tokens_prevent_created_at_change BEFORE UPDATE ON public.oauth_refresh_tokens FOR EACH ROW EXECUTE FUNCTION public.prevent_created_at_change();


--
-- Name: user_settings user_settings_prevent_created_at_change; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER user_settings_prevent_created_at_change BEFORE UPDATE ON public.user_settings FOR EACH ROW EXECUTE FUNCTION public.prevent_created_at_change();


--
-- Name: user_settings user_settings_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER user_settings_set_updated_at BEFORE UPDATE ON public.user_settings FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: user_slot_tokens user_slot_tokens_prevent_created_at_change; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER user_slot_tokens_prevent_created_at_change BEFORE UPDATE ON public.user_slot_tokens FOR EACH ROW EXECUTE FUNCTION public.prevent_created_at_change();


--
-- Name: user_slot_tokens user_slot_tokens_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER user_slot_tokens_set_updated_at BEFORE UPDATE ON public.user_slot_tokens FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: user_token_usage user_token_usage_prevent_any_update; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER user_token_usage_prevent_any_update BEFORE UPDATE ON public.user_token_usage FOR EACH ROW EXECUTE FUNCTION public.prevent_any_update();


--
-- Name: user_worker_events user_worker_events_prevent_any_update; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER user_worker_events_prevent_any_update BEFORE UPDATE ON public.user_worker_events FOR EACH ROW EXECUTE FUNCTION public.prevent_any_update();


--
-- Name: users users_prevent_created_at_change; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER users_prevent_created_at_change BEFORE UPDATE ON public.users FOR EACH ROW EXECUTE FUNCTION public.prevent_created_at_change();


--
-- Name: users users_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER users_set_updated_at BEFORE UPDATE ON public.users FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: auth_google auth_google_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_google
    ADD CONSTRAINT auth_google_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: auth_sessions auth_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_sessions
    ADD CONSTRAINT auth_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: data_blob_edges data_blob_edges_child_blob_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_blob_edges
    ADD CONSTRAINT data_blob_edges_child_blob_id_fkey FOREIGN KEY (child_blob_id) REFERENCES public.data_blobs(blob_id) ON DELETE CASCADE;


--
-- Name: data_blob_edges data_blob_edges_parent_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_blob_edges
    ADD CONSTRAINT data_blob_edges_parent_node_id_fkey FOREIGN KEY (parent_node_id) REFERENCES public.data_nodes(node_id) ON DELETE CASCADE;


--
-- Name: data_blob_edges data_blob_edges_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_blob_edges
    ADD CONSTRAINT data_blob_edges_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: data_blobs data_blobs_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_blobs
    ADD CONSTRAINT data_blobs_file_id_fkey FOREIGN KEY (file_id) REFERENCES public.data_files(file_id) ON DELETE CASCADE;


--
-- Name: data_blobs data_blobs_next_blob_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_blobs
    ADD CONSTRAINT data_blobs_next_blob_id_fkey FOREIGN KEY (next_blob_id) REFERENCES public.data_blobs(blob_id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: data_blobs data_blobs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_blobs
    ADD CONSTRAINT data_blobs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: data_files data_files_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_files
    ADD CONSTRAINT data_files_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: data_node_abstracts data_node_abstracts_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_node_abstracts
    ADD CONSTRAINT data_node_abstracts_node_id_fkey FOREIGN KEY (node_id) REFERENCES public.data_nodes(node_id) ON DELETE CASCADE;


--
-- Name: data_node_abstracts data_node_abstracts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_node_abstracts
    ADD CONSTRAINT data_node_abstracts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: data_node_edges data_node_edges_child_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_node_edges
    ADD CONSTRAINT data_node_edges_child_node_id_fkey FOREIGN KEY (child_node_id) REFERENCES public.data_nodes(node_id) ON DELETE CASCADE;


--
-- Name: data_node_edges data_node_edges_parent_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_node_edges
    ADD CONSTRAINT data_node_edges_parent_node_id_fkey FOREIGN KEY (parent_node_id) REFERENCES public.data_nodes(node_id) ON DELETE CASCADE;


--
-- Name: data_node_edges data_node_edges_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_node_edges
    ADD CONSTRAINT data_node_edges_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: data_node_weights data_node_weights_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_node_weights
    ADD CONSTRAINT data_node_weights_node_id_fkey FOREIGN KEY (node_id) REFERENCES public.data_nodes(node_id) ON DELETE CASCADE;


--
-- Name: data_node_weights data_node_weights_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_node_weights
    ADD CONSTRAINT data_node_weights_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: data_nodes data_nodes_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_nodes
    ADD CONSTRAINT data_nodes_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: oauth_access_tokens oauth_access_tokens_client_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_access_tokens
    ADD CONSTRAINT oauth_access_tokens_client_id_fkey FOREIGN KEY (client_id) REFERENCES public.oauth_clients(client_id) ON DELETE CASCADE;


--
-- Name: oauth_access_tokens oauth_access_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_access_tokens
    ADD CONSTRAINT oauth_access_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: oauth_authorization_grants oauth_authorization_grants_client_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_authorization_grants
    ADD CONSTRAINT oauth_authorization_grants_client_id_fkey FOREIGN KEY (client_id) REFERENCES public.oauth_clients(client_id) ON DELETE CASCADE;


--
-- Name: oauth_authorization_grants oauth_authorization_grants_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_authorization_grants
    ADD CONSTRAINT oauth_authorization_grants_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: oauth_refresh_tokens oauth_refresh_tokens_client_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_refresh_tokens
    ADD CONSTRAINT oauth_refresh_tokens_client_id_fkey FOREIGN KEY (client_id) REFERENCES public.oauth_clients(client_id) ON DELETE CASCADE;


--
-- Name: oauth_refresh_tokens oauth_refresh_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oauth_refresh_tokens
    ADD CONSTRAINT oauth_refresh_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_settings user_settings_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_settings
    ADD CONSTRAINT user_settings_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_slot_tokens user_slot_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_slot_tokens
    ADD CONSTRAINT user_slot_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_token_usage user_token_usage_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_token_usage
    ADD CONSTRAINT user_token_usage_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_worker_events user_worker_events_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_worker_events
    ADD CONSTRAINT user_worker_events_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict dbmate


--
-- Dbmate schema migrations
--

INSERT INTO public.schema_migrations (version) VALUES
    ('202605060001'),
    ('202605180001'),
    ('202605180002'),
    ('202605180003'),
    ('202605180004'),
    ('202605180005'),
    ('202605180006'),
    ('202605180007'),
    ('202605260001'),
    ('202605290001'),
    ('202606020001');
