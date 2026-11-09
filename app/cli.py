"""Flask CLI commands: `flask seed`, `flask create-admin`, `flask vapid-keys`, `flask cleanup-push`."""
import getpass

import click

from .extensions import db


def register_cli(app):
    @app.cli.command("seed")
    @click.option("--demo", is_flag=True, help="Also load DEMO road sections/points/reports (never in production).")
    def seed(demo):
        """Load reference data (roles, permissions, statuses, categories, teams, settings)."""
        from .seed import seed_demo, seed_reference
        seed_reference()
        click.echo("Reference data loaded.")
        if demo:
            seed_demo()
            click.echo("DEMO data loaded (illustrative — do not use in production).")

    @app.cli.command("create-admin")
    @click.option("--name", prompt="Full name")
    @click.option("--email", default="", help="E-mail (phone or e-mail required)")
    @click.option("--phone", default="", help="Phone (e.g. 0912345678)")
    @click.option("--role", type=click.Choice(["admin", "superadmin", "supervisor", "employee"]), default="superadmin")
    def create_admin(name, email, phone, role):
        """Create (or promote) an administrator account. The password is asked interactively."""
        from .models import Role, User
        from .utils.validators import normalize_phone
        phone = normalize_phone(phone) if phone else None
        email = email.strip().lower() or None
        if not (phone or email):
            raise click.UsageError("Provide --email or --phone")
        user = None
        if email:
            user = db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none()
        if user is None and phone:
            user = db.session.execute(db.select(User).filter_by(phone=phone)).scalar_one_or_none()
        pw = getpass.getpass("Password: ")
        if len(pw) < 10:
            raise click.UsageError("Administrator passwords must be at least 10 characters.")
        if pw != getpass.getpass("Repeat password: "):
            raise click.UsageError("Passwords do not match.")
        r = db.session.execute(db.select(Role).filter_by(code=role)).scalar_one_or_none()
        if r is None:
            raise click.UsageError("Roles not found — run `flask seed` first.")
        if user is None:
            user = User(full_name=name, email=email, phone=phone, locale="ar")
            db.session.add(user)
        user.set_password(pw)
        user.active = True
        if r not in user.roles:
            user.roles.append(r)
        db.session.commit()
        click.echo(f"Administrator ready: id={user.id} role={role}")

    @app.cli.command("vapid-keys")
    def vapid_keys():
        """Generate a VAPID key pair for Web Push (store the private key ONLY in .env)."""
        import base64

        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        key = ec.generate_private_key(ec.SECP256R1())
        priv = key.private_numbers().private_value.to_bytes(32, "big")
        pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
        click.echo(f"VAPID_PUBLIC_KEY={b64(pub)}")
        click.echo(f"VAPID_PRIVATE_KEY={b64(priv)}")

    @app.cli.command("cleanup-push")
    def cleanup_push():
        """Remove push subscriptions that repeatedly failed."""
        from .models import PushSubscription
        n = db.session.execute(db.delete(PushSubscription).where(PushSubscription.failure_count >= 5)).rowcount
        db.session.commit()
        click.echo(f"Removed {n} stale subscriptions.")
