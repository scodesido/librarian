# Backend Python style and conventions
Below is some guidance on how to write code for this repo. However, first and foremost, what the repo should be is defined by what the repo is.
Do always take a look at existing code and conventions in relevant or similar files, and use that as your main guidance. In particular,
- `backend/src/` The python code of the backend, including API and services.
- `backend/db/` The migrations and current schema of the DB the backend will interact with. Always take the migrations as source truth - the schema might be outdated.
- `docs/` The architectural documentation explaining the choices made in the codebase.
In case of conflict or doubt, ask.

As a general principle, you can edit source files in the repo. But for anything else - in particular, running commands - ask the user instead.

## Functions and files
We keep files and functions small, idiomatic, and hierarchical. It should be clear to a user what something does (this small file does what the name says it does)
and where to find it (meaningful folder hierarchy). The same applies to variable and function names. Consistency across the codebase matters enormously -
do ask the user in case of doubt about conventions.

Additionally, we make good use of modules. Rather than having lots of small modules in a largely flat setup, add submodules when it would help navigating
the code for a person visiting the repo for the first time. For instance, if a `settings.py` module defines a settings BaseModel, then any nested settings
modules should go in submodules. Or if an `auth.py` module provides an abstraction for an auth layer, concrete implementation also go into submodules.

## Classes
We try to avoid complex OOP patterns. Classes are fine, but typically these should be Pydantic models (i.e. "structs" in other languages),
with possibly helper methods that very directly map to the class. E.g. derived properties or cached properties, simple factory patterns
(e.g. creating a Client object from a Settings object, but the Client object should still be defined elsewhere.)

## Other
Do not use `_private_function` naming convention for functions.

Use always `from ... import ...` imports, if needed use aliases `... as ...`. Avoid raw `import ...`. Avoid `__init__.py` initializers when possible.


## API
The API endpoints should live in their own files under endpoints/. The folder structure should map to the API path structure.
Each terminal python module under endpoints/ represents a router. Each router can have more than one endpoint, but ideally not many.
The response and request models must live in the same file as the endpoints that use them. The same applies to other models
for specific use cases - we try to follow a logic of code locality, "define where you use".

# Database management
We use dbmate. All migrations must be created by the user, not yourself - if you need a new one, ask the user to create a new,
empty migration file (under backend/db/migrations/) and then fill it in as needed.

# Frontend React style

It is meant to be a simple frontend. The ideas about small files, descriptive names, and code locality still applies.
In fact, locality goes as far as avoiding the use of CSS, and having style live in the corresponding components.
Although this means - in the component definitions, not as ad-hoc changes in component usage.

We use a `my-module.tsx` convention for tsx files. Inside, this would declare a `MyModule` component.

# Docs
Documentation on architectural decisions should go as numbered markdown files in the `docs/` folder.
These describe, in historical order, architectural decisions - not tiny implementation details.
E.g. why a certain tech or pattern is used, more than how it is implemented. 
The goal is for subsequent modifications to the project to have a clear idea of what the project
is meant to do, and how the pieces fit together.
Whenever new changes are proposed, corresponding docs should be added. If changes are decided on an existing
piece of architecture, of course, the doc of the current workload can still be modified.
