\restrict dbmate

-- Dumped from database version 17.9 (Debian 17.9-1.pgdg12+1)
-- Dumped by pg_dump version 17.9 (Debian 17.9-0+deb13u1)

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


--
-- Name: tree_edges_check_height(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.tree_edges_check_height() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    parent_height INT;
    child_height  INT;
BEGIN
    SELECT height INTO parent_height FROM tree_nodes WHERE node_id = NEW.parent_id;
    SELECT height INTO child_height  FROM tree_nodes WHERE node_id = NEW.child_id;
    IF parent_height IS DISTINCT FROM child_height + 1 THEN
        RAISE EXCEPTION
            'tree_edges height mismatch: parent height %, child height %, '
            'expected parent height %',
            parent_height, child_height, child_height + 1;
    END IF;
    RETURN NEW;
END;
$$;


--
-- Name: tree_edges_delete_orphan_parent(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.tree_edges_delete_orphan_parent() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM tree_edges WHERE parent_id = OLD.parent_id
    ) THEN
        DELETE FROM tree_nodes WHERE node_id = OLD.parent_id;
    END IF;
    RETURN NULL;
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
-- Name: data_blobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.data_blobs (
    blob_id bigint NOT NULL,
    file_id bigint NOT NULL,
    start integer NOT NULL,
    "end" integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
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
    state text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT data_files_source_check CHECK ((source = 'GDRIVE'::text)),
    CONSTRAINT data_files_state_check CHECK ((state = ANY (ARRAY['PENDING'::text, 'PROCESSING'::text, 'READY'::text, 'FAILED'::text]))),
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
-- Name: node_embeddings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.node_embeddings (
    node_id bigint NOT NULL,
    field text NOT NULL,
    model_id text NOT NULL,
    embedding public.vector(1024) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    version character varying NOT NULL
);


--
-- Name: tree_edges; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tree_edges (
    edge_id bigint NOT NULL,
    parent_id bigint NOT NULL,
    child_id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT tree_edges_check CHECK ((parent_id <> child_id))
);


--
-- Name: tree_edges_edge_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tree_edges_edge_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tree_edges_edge_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tree_edges_edge_id_seq OWNED BY public.tree_edges.edge_id;


--
-- Name: tree_nodes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tree_nodes (
    node_id bigint NOT NULL,
    user_id bigint NOT NULL,
    blob_id bigint,
    abstract jsonb,
    height integer NOT NULL,
    state text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT tree_nodes_height_check CHECK ((height >= 0)),
    CONSTRAINT tree_nodes_leaf_invariant CHECK ((((height = 0) AND (blob_id IS NOT NULL) AND (state = 'READY'::text)) OR ((height > 0) AND (blob_id IS NULL)))),
    CONSTRAINT tree_nodes_state_check CHECK ((state = ANY (ARRAY['PENDING'::text, 'PROCESSING'::text, 'READY'::text, 'FAILED'::text])))
);


--
-- Name: tree_nodes_node_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tree_nodes_node_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tree_nodes_node_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tree_nodes_node_id_seq OWNED BY public.tree_nodes.node_id;


--
-- Name: tree_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tree_state (
    user_id bigint NOT NULL,
    level integer DEFAULT 0 NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT tree_state_level_check CHECK ((level >= 0))
);


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
-- Name: data_blobs blob_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_blobs ALTER COLUMN blob_id SET DEFAULT nextval('public.data_blobs_blob_id_seq'::regclass);


--
-- Name: data_files file_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_files ALTER COLUMN file_id SET DEFAULT nextval('public.data_files_file_id_seq'::regclass);


--
-- Name: tree_edges edge_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tree_edges ALTER COLUMN edge_id SET DEFAULT nextval('public.tree_edges_edge_id_seq'::regclass);


--
-- Name: tree_nodes node_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tree_nodes ALTER COLUMN node_id SET DEFAULT nextval('public.tree_nodes_node_id_seq'::regclass);


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
-- Name: node_embeddings node_embeddings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.node_embeddings
    ADD CONSTRAINT node_embeddings_pkey PRIMARY KEY (node_id, field, model_id);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);


--
-- Name: tree_edges tree_edges_parent_id_child_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tree_edges
    ADD CONSTRAINT tree_edges_parent_id_child_id_key UNIQUE (parent_id, child_id);


--
-- Name: tree_edges tree_edges_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tree_edges
    ADD CONSTRAINT tree_edges_pkey PRIMARY KEY (edge_id);


--
-- Name: tree_nodes tree_nodes_blob_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tree_nodes
    ADD CONSTRAINT tree_nodes_blob_id_key UNIQUE (blob_id);


--
-- Name: tree_nodes tree_nodes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tree_nodes
    ADD CONSTRAINT tree_nodes_pkey PRIMARY KEY (node_id);


--
-- Name: tree_state tree_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tree_state
    ADD CONSTRAINT tree_state_pkey PRIMARY KEY (user_id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


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
-- Name: idx_data_blobs_file_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_data_blobs_file_id ON public.data_blobs USING btree (file_id);


--
-- Name: idx_data_files_user_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_data_files_user_state ON public.data_files USING btree (user_id, state);


--
-- Name: idx_tree_edges_child_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tree_edges_child_id ON public.tree_edges USING btree (child_id);


--
-- Name: idx_tree_nodes_user_height_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tree_nodes_user_height_state ON public.tree_nodes USING btree (user_id, height, state);


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
-- Name: data_blobs data_blobs_prevent_created_at_change; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER data_blobs_prevent_created_at_change BEFORE UPDATE ON public.data_blobs FOR EACH ROW EXECUTE FUNCTION public.prevent_created_at_change();


--
-- Name: data_blobs data_blobs_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER data_blobs_set_updated_at BEFORE UPDATE ON public.data_blobs FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: data_files data_files_prevent_created_at_change; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER data_files_prevent_created_at_change BEFORE UPDATE ON public.data_files FOR EACH ROW EXECUTE FUNCTION public.prevent_created_at_change();


--
-- Name: data_files data_files_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER data_files_set_updated_at BEFORE UPDATE ON public.data_files FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: tree_edges tree_edges_check_height; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER tree_edges_check_height BEFORE INSERT OR UPDATE ON public.tree_edges FOR EACH ROW EXECUTE FUNCTION public.tree_edges_check_height();


--
-- Name: tree_edges tree_edges_delete_orphan_parent; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER tree_edges_delete_orphan_parent AFTER DELETE ON public.tree_edges FOR EACH ROW EXECUTE FUNCTION public.tree_edges_delete_orphan_parent();


--
-- Name: tree_nodes tree_nodes_prevent_created_at_change; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER tree_nodes_prevent_created_at_change BEFORE UPDATE ON public.tree_nodes FOR EACH ROW EXECUTE FUNCTION public.prevent_created_at_change();


--
-- Name: tree_nodes tree_nodes_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER tree_nodes_set_updated_at BEFORE UPDATE ON public.tree_nodes FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: tree_state tree_state_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER tree_state_set_updated_at BEFORE UPDATE ON public.tree_state FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


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
-- Name: data_blobs data_blobs_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_blobs
    ADD CONSTRAINT data_blobs_file_id_fkey FOREIGN KEY (file_id) REFERENCES public.data_files(file_id) ON DELETE CASCADE;


--
-- Name: data_files data_files_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.data_files
    ADD CONSTRAINT data_files_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: node_embeddings node_embeddings_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.node_embeddings
    ADD CONSTRAINT node_embeddings_node_id_fkey FOREIGN KEY (node_id) REFERENCES public.tree_nodes(node_id) ON DELETE CASCADE;


--
-- Name: tree_edges tree_edges_child_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tree_edges
    ADD CONSTRAINT tree_edges_child_id_fkey FOREIGN KEY (child_id) REFERENCES public.tree_nodes(node_id) ON DELETE CASCADE;


--
-- Name: tree_edges tree_edges_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tree_edges
    ADD CONSTRAINT tree_edges_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.tree_nodes(node_id) ON DELETE CASCADE;


--
-- Name: tree_nodes tree_nodes_blob_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tree_nodes
    ADD CONSTRAINT tree_nodes_blob_id_fkey FOREIGN KEY (blob_id) REFERENCES public.data_blobs(blob_id) ON DELETE CASCADE;


--
-- Name: tree_nodes tree_nodes_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tree_nodes
    ADD CONSTRAINT tree_nodes_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: tree_state tree_state_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tree_state
    ADD CONSTRAINT tree_state_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict dbmate


--
-- Dbmate schema migrations
--

INSERT INTO public.schema_migrations (version) VALUES
    ('20260506075609'),
    ('20260507093602'),
    ('20260507141158'),
    ('20260507142213'),
    ('20260507142223');
