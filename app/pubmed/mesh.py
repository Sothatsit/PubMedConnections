from typing import Optional

from lxml import etree
import os
import glob

from app.pubmed.extract_xml import extract_mesh_headings
from app.pubmed.source_files import DTDResolver
from app.pubmed.sink_db import PubmedCacheConn


def create_mesh_parser(directory: str) -> etree.XMLParser:
    parser = etree.XMLParser(
        remove_blank_text=True,
        remove_comments=True,
        remove_pis=True,
        collect_ids=False,
        load_dtd=False,
        dtd_validation=False,
        attribute_defaults=False
    )
    parser.resolvers.add(DTDResolver(directory, "https://www.nlm.nih.gov/databases/dtd"))
    return parser


def extract_desc_file_year(desc_file_name: str):
    """ Extracts the year of desc*.xml files. """
    desc_file_name = os.path.basename(desc_file_name)
    if not desc_file_name.startswith("desc"):
        raise Exception("File name does not start with desc, {}".format(desc_file_name))
    if not desc_file_name.endswith(".xml"):
        raise Exception("File name does not end with .xml, {}".format(desc_file_name))

    return int(desc_file_name[len("desc"):-len(".xml")])


def process_mesh_headings(target_directory: str, conn: PubmedCacheConn):
    directory = os.path.join(target_directory, "mesh")

    # Find the XML file under /data/mesh/
    desc_files = glob.glob(os.path.join(directory, "desc*.xml"))
    latest_file: Optional[str] = None
    latest_year: Optional[int] = None
    for file in desc_files:
        year = extract_desc_file_year(file)
        if latest_file is None or year > latest_year:
            latest_file = file
            latest_year = year

    if latest_file is None:
        raise Exception("No MESH heading XML file found in the format desc*.xml")

    # Parse the XML
    print(f"PubMedExtract: Parsing MeSH headings from {latest_file}...")
    parser = create_mesh_parser(directory)
    tree = etree.parse(latest_file, parser)

    # Extract the MeshHeading objects
    headings = extract_mesh_headings(tree)

    # Add to the database
    print(f"PubMedExtract: Adding {len(headings)} MeSH headings to the database...")
    conn.insert_mesh_heading_batch(headings)

    print(f"PubMedExtract: Successfully added {len(headings)} MESH headings to database.\n")
