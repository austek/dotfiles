---
title: Use the Typestate Pattern to Encode State Machine Invariants
impact: HIGH
impactDescription: Turns invalid state transitions into compile errors instead of runtime checks
tags: [api-design, typestate, state-machine, type-safety]
---

# Use the Typestate Pattern to Encode State Machine Invariants [HIGH]

## Description
A state machine represented as one type with a runtime `state: State` field relies on every method remembering to check that field before acting — forgetting a check is a compile-clean bug that only surfaces when the wrong sequence of calls happens at runtime. The typestate pattern instead gives each state its own distinct type (`Connection<Disconnected>`, `Connection<Authenticated>`), and defines each method only on the states where it's valid to call. A method that requires authentication simply doesn't exist on `Connection<Connected>` — calling it too early is not a runtime error, it's a compile error.

## Bad Example
```rust
struct Connection {
    state: ConnectionState,
    socket: Option<TcpStream>,
}

enum ConnectionState { Disconnected, Connected, Authenticated }

impl Connection {
    fn send(&mut self, data: &[u8]) -> Result<(), Error> {
        // Runtime check — can fail if called in the wrong state
        if self.state != ConnectionState::Authenticated {
            return Err(Error::NotAuthenticated);
        }
        self.socket.as_mut().unwrap().write_all(data)?;
        Ok(())
    }
}

// Bug: forgot to authenticate — compiles fine, fails at runtime
let mut conn = Connection::new();
conn.connect()?;
conn.send(b"data")?;  // Runtime error: NotAuthenticated
```

## Good Example
```rust
struct Disconnected;
struct Connected { socket: TcpStream }
struct Authenticated { socket: TcpStream, session: Session }

struct Connection<State> { state: State }

impl Connection<Disconnected> {
    fn connect(self, addr: &str) -> Result<Connection<Connected>, Error> {
        let socket = TcpStream::connect(addr)?;
        Ok(Connection { state: Connected { socket } })
    }
}

impl Connection<Connected> {
    fn authenticate(self, password: &str) -> Result<Connection<Authenticated>, Error> {
        let session = do_auth(&self.state.socket, password)?;
        Ok(Connection { state: Authenticated { socket: self.state.socket, session } })
    }
}

impl Connection<Authenticated> {
    fn send(&mut self, data: &[u8]) -> Result<(), Error> {
        // No runtime check needed — the type guarantees we're authenticated
        self.state.socket.write_all(data)?;
        Ok(())
    }
}

let conn = Connection::new().connect("server:8080")?;
conn.send(b"data");  // Compile error! send() doesn't exist on Connection<Connected>

let mut conn = Connection::new().connect("server:8080")?.authenticate("secret")?;
conn.send(b"data")?;  // Works — type is Connection<Authenticated>
```

## Notes
- Each state-transition method consumes `self` and returns the next state's type (`fn authenticate(self) -> Result<Connection<Authenticated>, Error>`), which also prevents accidentally reusing a connection in a state it has already moved past.
- The same technique builds a builder that enforces required fields at compile time — a `RequestBuilder<NoUrl>` simply has no `build()` method; only `RequestBuilder<WithUrl>` does, so calling `build()` before `url()` is a compile error rather than a runtime `Result::Err`.
- The cost is real: more types, more `impl` blocks, and a steeper learning curve for contributors unfamiliar with the pattern — reserve it for state machines where an invalid transition is costly (a database transaction, a network handshake) rather than applying it reflexively to every stateful type.
- A transaction type (`Transaction<NotStarted>`, `Transaction<InProgress>`, `Transaction<Committed>`) is a canonical example: `execute()` only exists on `InProgress`, and `commit()`/`rollback()` consume it, making a double-commit or a commit-before-begin unrepresentable.
- Typestate composes with sealed traits when you want the state types themselves to be uninstantiable outside your crate, preventing external code from fabricating a state your invariants don't actually guarantee.

## References
- [api-builder-pattern](api-builder-pattern.md)
- [api-parse-dont-validate](api-parse-dont-validate.md)
- [api-sealed-trait](api-sealed-trait.md)
