import re
import os
import click
import json

from loguru import logger

from tiktokcomment import TiktokComment
from tiktokcomment.typing import Comments

__title__ = 'TikTok Comment Scrapper'
__version__ = '2.0.0'

@click.command(
    help=__title__
)
@click.version_option(
    version=__version__,
    prog_name=__title__
)
@click.option(
    "--aweme_id",
    help='id video tiktok',
    callback=lambda _, __, value: match.group(0) if (match := re.match(r"^\d+$", value)) else None
)
@click.option(
    "--output",
    default='data/',
    help='directory output data'
)
def main(
    aweme_id: str,
    output: str
):
    if not aweme_id:
        raise ValueError('example id : 7418294751977327878')

    logger.info('start scrap comments %s' % aweme_id)

    comments: Comments = TiktokComment()(
        aweme_id=aweme_id
    )

    # ------------------------------
    # FIX 1: Normalizar ruta
    # ------------------------------
    output_dir = output.rstrip("/\\")  # quitar barras finales

    # si quedó vacío, usar el nombre base
    if output_dir == "":
        output_dir = "data"

    # crear directorio si no existe
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    # ------------------------------
    # FIX 2: Crear path final JSON
    # ------------------------------
    final_path = os.path.join(output_dir, f"{aweme_id}.json")

    # ------------------------------
    # FIX 3: Guardar en UTF-8 sin errores
    # ------------------------------
    with open(final_path, 'w', encoding='utf-8') as f:
        json.dump(comments.dict, f, ensure_ascii=False, indent=4)

    logger.info('save comments %s on %s' % (aweme_id, final_path))


if __name__ == '__main__':
    main()
