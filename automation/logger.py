import logging
import os
from datetime import datetime


os.makedirs("logs", exist_ok=True)


filename = datetime.now().strftime(
    "logs/%Y%m%d.log"
)


logging.basicConfig(

    filename=filename,

    level=logging.INFO,

    format="%(asctime)s | %(levelname)s | %(message)s"

)


logger = logging.getLogger("FloodAutomation")