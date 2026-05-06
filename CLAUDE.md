# Python style and conventions
Below is some guidance on how to write code for this repo. However, first and foremost, what the repo should be is defined by what the repo is.
Do always take a look at existing code and conventions in relevant or similar files, and use that as your main guidance. In case of conflict or doubt, ask.

## Functions and files
We keep files and functions small, idiomatic, and hierarchical. It should be clear to a user what something does (this small file does what the name says it does)
and where to find it (meaningful folder hierarchy). The same applies to variable and function names. Consistency across the codebase matters enormously -
do ask the user in case of doubt about conventions.

## Classes
We try to avoid complex OOP patterns. Classes are fine, but typically these should be Pydantic models (i.e. "structs" in other languages),
with possibly helper methods that very directly map to the class. E.g. derived properties or cached properties, simple factory patterns
(e.g. creating a Client object from a Settings object, but the Client object should still be defined elsewhere.)

Do not use `_private_function` naming convention for functions.

## API
The API endpoints should live in their own files under endpoints/. The folder structure should map to the API path structure.
Each terminal python module under endpoints/ represents a router. Each router can have more than one endpoint, but ideally not many.
The response and request models must live in the same file as the endpoints that use them. But to avoid cluttering, any reusable
nested models used should be in src/librarian/types.

# Database management
We use dbmate. All migrations must be created by the user, not yourself - if you need a new one, ask the user to create a new,
empty migration file (under backend/db/migrations/) and then fill it in as needed.
