"""
Encriptación AES-256 para mensajes de chat
Usa Fernet con clave compartida desde env/config.
"""

import os
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import dotenv_values
from flask import current_app


def _load_key_from_known_env_files():
    """Intenta leer ENCRYPTION_KEY desde .env conocidos."""
    candidates = [
        Path(__file__).resolve().parents[1] / '.env',
        Path('/src/.env'),
    ]

    for env_path in candidates:
        try:
            if not env_path.exists():
                continue
            values = dotenv_values(env_path)
            key = values.get('ENCRYPTION_KEY')
            if key:
                return str(key)
        except Exception:
            continue

    return None


class MessageEncryption:
    """Encripta y desencripta mensajes usando Fernet."""

    @staticmethod
    def get_key():

        try:
            key = current_app.config.get('ENCRYPTION_KEY')
            if key:
                if isinstance(key, str):
                    key = key.encode()
                return key
        except RuntimeError:
            pass

        key = os.environ.get('ENCRYPTION_KEY')
        if key:
            try:
                current_app.config['ENCRYPTION_KEY'] = key
            except RuntimeError:
                pass

        if not key:
            key = _load_key_from_known_env_files()
            if key:
                os.environ['ENCRYPTION_KEY'] = key
                try:
                    current_app.config['ENCRYPTION_KEY'] = key
                except RuntimeError:
                    pass

        if not key:
            raise RuntimeError("ENCRYPTION_KEY no está configurada.")

        if isinstance(key, str):
            key = key.encode()

        return key

    @staticmethod
    def encrypt(plaintext):
        if not plaintext:
            return plaintext

        try:
            key = MessageEncryption.get_key()
            cipher = Fernet(key)

            if isinstance(plaintext, str):
                plaintext = plaintext.encode('utf-8')

            token = cipher.encrypt(plaintext)
            return token.decode('utf-8')
        except Exception:
            raise

    @staticmethod
    def decrypt(ciphertext):
        if not ciphertext:
            return ciphertext

        try:
            key = MessageEncryption.get_key()
            cipher = Fernet(key)

            if isinstance(ciphertext, str):
                ciphertext = ciphertext.encode('utf-8')

            plaintext = cipher.decrypt(ciphertext)
            return plaintext.decode('utf-8')
        except Exception:
            raise


# ====================== HELPERS GLOBALES ======================

def encrypt_message(text):
    """Helper: Encriptar mensaje"""
    return MessageEncryption.encrypt(text)


def decrypt_message(token):
    """Helper: Desencriptar mensaje"""
    return MessageEncryption.decrypt(token)


def get_decrypted_content(msg, session=None):
    """Convierte contenido legacy a encrypted y devuelve texto desencriptado."""
    try:
        if hasattr(msg, 'content_encrypted') and msg.content_encrypted:
            try:
                decrypted = decrypt_message(msg.content_encrypted)
                return decrypted
            except Exception as decrypt_error:
                fallback_plain = (msg.content or "") if hasattr(msg, 'content') else ""
                if fallback_plain:
                    print(f"[ENC] ⚠️ Mensaje {msg.id}: falló decrypt, usando fallback content plano")
                    return fallback_plain
                print(f"[ENC] ❌ Mensaje {msg.id}: sin fallback tras error decrypt: {decrypt_error}")
                return ""

        if hasattr(msg, 'content') and msg.content:
            original_content = msg.content
            print(f"[ENC] 🔄 Mensaje {msg.id}: MIGRANDO - encontrado content sin encriptar, auto-encriptando...")

            try:
                encrypted = encrypt_message(original_content)
                msg.content_encrypted = encrypted

                if session:
                    try:
                        session.add(msg)
                        session.flush()
                    except Exception as db_error:
                        print(f"[ENC] ⚠️ Mensaje {msg.id}: error guardando encriptación: {db_error}")
                        try:
                            session.rollback()
                        except Exception:
                            pass

                return original_content
            except Exception as encrypt_error:
                print(f"[ENC] ❌ Mensaje {msg.id}: error encriptando: {encrypt_error}")
                return original_content

        print(f"[ENC] ⚠️ Mensaje {msg.id}: sin contenido en content ni content_encrypted")
        return ""

    except Exception as e:
        print(f"[ENC] ❌ CRÍTICO en get_decrypted_content(): {e}")
        import traceback
        traceback.print_exc()
        return ""
