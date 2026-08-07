IMPORTANT DEVELOPMENT RULES

1. Build this project incrementally.
2. Do NOT generate the entire application in one step.
3. First create the architecture and project structure.
4. Then implement backend foundation.
5. Then database models and migrations.
6. Then persona compiler.
7. Then debate engine.
8. Then judge engine.
9. Then frontend.
10. Then streaming.
11. Then evaluation dashboard.

Before implementing each phase:

- inspect existing code
- preserve working functionality
- identify dependencies
- explain what will be changed
- implement
- run tests
- fix errors
- verify the application

Do not rewrite working files unnecessarily.

Keep business logic separate from API routes.

Keep LLM prompts in dedicated prompt modules.

Never expose API keys to the frontend.

Never hard-code provider-specific logic into the debate engine.

Use environment variables for model configuration.

Use typed Pydantic schemas for LLM structured output.

Use async APIs where appropriate.

Implement robust error handling.

Add logging around LLM calls.

Use database migrations.

Write unit tests for:

- persona schema validation
- persona compilation
- prompt generation
- debate state transitions
- judge result validation

Do not add unnecessary dependencies.

Do not implement authentication, RAG, vector databases,
voice, avatars, or fine-tuning in the MVP.

The MVP must remain small and functional.
