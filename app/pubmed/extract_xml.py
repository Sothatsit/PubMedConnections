"""
Contains functions to extract PubMed data from XML files.
"""
import datetime
import traceback
from typing import Optional

from lxml import etree

from app.pubmed.model import Author, Article, Journal


MONTHS = [
    ("jan", 31),
    ("feb", 29),
    ("mar", 31),
    ("apr", 30),
    ("may", 31),
    ("jun", 30),
    ("jul", 31),
    ("aug", 31),
    ("sep", 30),
    ("oct", 31),
    ("nov", 30),
    ("dec", 31),
]
ABBREV_MONTH_NAMES_LOWER = [abbrev for abbrev, _ in MONTHS]
MAX_DAYS_IN_MONTH = [max_days for _, max_days in MONTHS]


def extract_single_node_by_tag(node, tag: str):
    for child in node:
        if child.tag == tag:
            return child
    return None


def parse_month(text: str) -> int:
    """
    Parses either a number in the range [1, 12], or a 3-letter month
    abbreviation and converts it to a number in the range [1, 12].
    """
    try:
        month = int(text)
        if month < 1 or month > 12:
            raise Exception("Unknown month: {}".format(text))

        return month
    except ValueError:
        pass

    try:
        return ABBREV_MONTH_NAMES_LOWER.index(text.lower()) + 1
    except ValueError:
        raise Exception("Unknown month: {}".format(text))


def parse_medline_date(medline_date: str) -> datetime.date:
    """
    Does its best to parse a <MedlineDate> value.
    The format of these dates is specified to be unspecified.
    Therefore, we can only try our best based on example values.
    """

    # Take left-hand side from date ranges such as:
    #   * 1998 Dec-1999 Jan   ->  1998 Dec
    #   * 2000 Spring-Summer  ->  2000 Spring
    #   * 2000 Nov-Dec        ->  2000 Nov
    #   * 2000 Dec 23- 30     ->  2000 Dec 23
    try:
        dash_index = medline_date.index("-")
        return parse_medline_date(medline_date[:dash_index])
    except ValueError:
        pass

    # Split the date into parts.
    parts = medline_date.split()

    # We always expect YYYY to start.
    year = int(parts[0])
    if len(parts) == 1:
        return datetime.date(year, 1, 1)

    # Next, we expect a month or season.
    try:
        month = parse_month(parts[1])
        if len(parts) == 2:
            return datetime.date(year, month, 1)
    except Exception as e:
        # Probably a season, ignore the rest and just use the year.
        # We would have to know whether the date was from the northern
        # or southern hemisphere to make sense of seasons...
        return datetime.date(year, 1, 1)

    # Next, we expect a day.
    try:
        day = int(parts[2])
        max_days = MAX_DAYS_IN_MONTH[month - 1]
        if day < 1 or day > max_days:
            # Ignore invalid days.
            return datetime.date(year, month, 1)

    except ValueError:
        # Ignore invalid days.
        return datetime.date(year, month, 1)

    # Ignore anything else in the string, and just use what we have gathered so far.
    return datetime.date(year, month, day)


def extract_date(date_node) -> datetime.date:
    """
    Extracts a date from one of <DateCreated>, <DateCompleted>, or <DateRevised>.
    """
    medline_date = None
    year: Optional[int] = None
    month: Optional[int] = None
    day: Optional[int] = None
    for node in date_node:
        tag = node.tag
        if tag == "Year":
            year = int(node.text)
        elif tag == "Month":
            month = parse_month(node.text)
        elif tag == "Day":
            day = int(node.text)
        elif tag == "MedlineDate":
            medline_date = node.text

    if year is None:
        if medline_date is not None:
            return parse_medline_date(medline_date)
        raise Exception("Date must contain either a <Year> or a <MedlineDate>")

    if month is None:
        month = 1
    if day is None:
        day = 1

    return datetime.date(year, month, day)


def extract_author(author_node) -> Author:
    """
    Extracts an author's information from an <Author> node.
    This does its best to canonicalize the names of authors into a standard format.
    """
    last_name = None
    fore_name = None
    initials = None
    suffix = None
    collective_name = None
    for node in author_node:
        tag = node.tag
        if tag == "LastName":
            last_name = node.text
        elif tag == "ForeName":
            fore_name = node.text
        elif tag == "Initials":
            initials = node.text
        elif tag == "Suffix":
            suffix = node.text
        elif tag == "CollectiveName":
            collective_name = node.text

    return Author.generate_from_name_pieces(last_name, fore_name, initials, suffix, collective_name)


def extract_authors(author_list_node) -> list[Author]:
    """
    Reads all the authors from an <AuthorList>.
    """
    seen_authors = set()  # Some articles can contain duplicate authors, hence the set.
    authors = []
    if author_list_node is not None:
        for author_node in author_list_node:
            if author_node.tag != "Author":
                continue

            author = extract_author(author_node)
            if author.full_name not in seen_authors:
                seen_authors.add(author.full_name)
                authors.append(author)

    return authors


def canonicalize_issn(issn: str) -> str:
    if len(issn) == 8:
        return issn
    if len(issn) == 9 and issn[4] == "-":
        return issn[:4] + issn[5:]

    raise Exception("Unrecognised ISSN: {}".format(issn))


def extract_journal_issue(journal_issue_node):
    """
    Extracts the volume and issue from a <JournalIssue>
    """
    volume = None
    issue = None
    pub_date_node = None
    for node in journal_issue_node:
        tag = node.tag
        if tag == "Volume":
            volume = node.text
        elif tag == "Issue":
            issue = node.text
        elif tag == "PubDate":
            pub_date_node = node

    if pub_date_node is None:
        raise Exception("Journal is missing a <PubDate>")

    date = extract_date(pub_date_node)
    return volume, issue, date


def extract_journal(journal_node) -> Journal:
    """
    Extracts a journal from <Journal>.
    """
    issn = None
    issn_linking = None
    iso_abbrev = None
    journal_issue_node = None
    title = None
    for node in journal_node:
        tag = node.tag
        if tag == "ISSN":
            issn = canonicalize_issn(node.text)
        elif tag == "ISSNLinking":
            issn_linking = canonicalize_issn(node.text)
        elif tag == "JournalIssue":
            journal_issue_node = node
        elif tag == "Title":
            title = node.text
        elif tag == "ISOAbbreviation":
            iso_abbrev = node.text

    if journal_issue_node is None:
        raise Exception("Journal is missing a <JournalIssue>")
    if title is None:
        raise Exception("Journal is missing a <Title>")

    issn = issn_linking if issn is None else issn

    volume, issue, date = extract_journal_issue(journal_issue_node)
    return Journal.generate(iso_abbrev, issn, title, volume, issue, date)


def extract_article(pmid: int, date: datetime.date, article_node):
    """
    Extracts the details of an article from an <Article> node.
    """
    english_title = None
    original_title = None
    author_list_node = None
    journal_node = None
    for node in article_node:
        tag = node.tag
        if tag == "ArticleTitle":
            english_title = node.text
        elif tag == "VernacularTitle":
            original_title = node.text
        elif tag == "AuthorList":
            author_list_node = node
        elif tag == "Journal":
            journal_node = node

    if journal_node is None:
        raise Exception("Article is missing <Journal>")

    article = Article.generate(
        pmid=pmid,
        date=date,
        english_title=english_title,
        original_title=original_title
    )
    article.journal = extract_journal(journal_node)

    if author_list_node is not None:
        article.authors = extract_authors(author_list_node)
    else:
        article.authors = []

    return article


def extract_citation(citation_node) -> Optional[Article]:
    """
    Extracts the details of an article from a <MedlineCitation> node.
    """
    pmid = None
    date_created_node = None
    date_completed_node = None
    date_revised_node = None
    article_node = None
    for node in citation_node:
        tag = node.tag
        if tag == "PMID":
            # This ignores the versioning of articles.
            pmid = int(node.text)
        elif tag == "Article":
            article_node = node
        elif tag == "DateCreated":
            date_created_node = node
        elif tag == "DateCompleted":
            date_completed_node = node
        elif tag == "DateRevised":
            date_revised_node = node

    # We want the earliest date we have available.
    date_node = date_created_node
    if date_node is None:
        date_node = date_completed_node
    if date_node is None:
        date_node = date_revised_node

    if pmid is None:
        raise Exception("Citation is missing a <PMID>")
    if article_node is None:
        raise Exception("Citation is missing an <Article>")
    if date_node is None:
        raise Exception("Citation does not contain a <DateCreated>, <DateCompleted>, nor a <DateRevised>")

    date = extract_date(date_node)
    return extract_article(pmid, date, article_node)


def extract_articles(tree) -> list[Article]:
    """
    Takes in a parsed PubMed data file object, and extracts
    the data that we are interested in from it.
    """
    root = tree.getroot()
    articles = []
    for index, pubmed_article_node in enumerate(root):
        if pubmed_article_node.tag != "PubmedArticle":
            continue

        try:
            citation_node = extract_single_node_by_tag(pubmed_article_node, "MedlineCitation")
            article = extract_citation(citation_node)
            if article is None:
                continue

            articles.append(article)
        except Exception as e:
            traceback.print_exc()
            try:
                with open("error.node.txt", "wt") as f:
                    f.write("{} occurred while extracting data around:\n{}".format(
                        type(e).__name__,
                        etree.tostring(
                            pubmed_article_node,
                            pretty_print=True,
                            encoding="utf8"
                        ).decode("utf8")
                    ))

                    # TODO : REMOVE
                    break

            except Exception as e2:
                traceback.print_exc()

    return articles
