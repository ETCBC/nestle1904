import re
from lxml import etree
from io import BytesIO

from tf.core.helpers import console
from tf.core.files import initTree, unexpanduser as ux

from tf.convert.helpers import NEST


def convertTaskCustom(self):
    """Implementation of the "convert" task.

    It sets up the `tf.convert.walker` machinery and runs it.

    Returns
    -------
    boolean
        Whether the conversion was successful.
    """
    if not self.good:
        return

    verbose = self.verbose
    tfPath = self.tfPath
    xmlPath = self.xmlPath

    if verbose == 1:
        console(f"XML to TF converting: {ux(xmlPath)} => {ux(tfPath)}")

    slotType = "w"
    otext = {
        "fmt:text-orig-full": "{text}{after}",
        "sectionTypes": "book,chapter,verse",
        "sectionFeatures": "book_short,chapter,verse",
    }
    intFeatures = {
        "chapter",
        "verse",
        "book_num",
        "sentence_number",
        "nodeId",
        "strong",
        "word_in_verse",
        "empty",
    }
    featureMeta = dict(
        book_num=dict(
            description="NT book number (Matthew=1, Mark=2, ..., Revelation=27)"
        ),
        book_short=dict(description="Book name (abbreviated)"),
        sentence_number=dict(description="Sentence number (counted per chapter)"),
        Rule=dict(description="Clause rule"),
        appositioncontainer=dict(description="Apposition container"),
        articular=dict(description="Articular"),
        class_wg=dict(description="Syntactical class"),
        clauseType=dict(description="Type of clause"),
        cltype=dict(description="Type of clause"),
        junction=dict(description="Type of junction"),
        nodeId=dict(description="Node ID (as in the XML source data"),
        role_wg=dict(description="Role"),
        rule=dict(description="Syntactical rule"),
        type_wg=dict(description="Syntactical type"),
        text=dict(description="the text of a word"),
        after=dict(description="After the end of the word"),
        book=dict(description="Book name (abbreviated)"),
        case=dict(description="Type of case"),
        chapter=dict(description="Number of the chapter"),
        class_w=dict(description="Morphological class"),
        degree=dict(description="Degree"),
        discontinuous=dict(description="Discontinuous"),
        domain=dict(description="domain"),
        frame=dict(description="frame"),
        gender=dict(description="gender"),
        gloss=dict(description="gloss"),
        id=dict(description="xml iD"),
        lemma=dict(description="lemma"),
        ln=dict(description="ln"),
        mood=dict(description="verbal mood"),
        morph=dict(description="morph"),
        normalized=dict(description="lemma normalized"),
        number=dict(description="number"),
        person=dict(description="person"),
        ref=dict(description="biblical reference with word counting"),
        referent=dict(description="number of referent"),
        role_w=dict(description="role"),
        strong=dict(description="strong number"),
        subjref=dict(description="number"),
        tense=dict(description="Verbal tense"),
        type_w=dict(description="Morphological type"),
        unicode=dict(description="lemma in unicode characters"),
        verse=dict(description="verse"),
        voice=dict(description="Verbal voice"),
        word_in_verse=dict(description="number of word"),
        empty=dict(description="whether a slot has been inserted in an empty element"),
    )
    self.intFeatures = intFeatures
    self.featureMeta = featureMeta

    tfVersion = self.tfVersion
    xmlVersion = self.xmlVersion
    generic = self.generic
    generic["sourceFormat"] = "XML"
    generic["version"] = tfVersion
    generic["xmlVersion"] = xmlVersion

    initTree(tfPath, fresh=True, gentle=True)

    cv = self.getConverter()

    self.good = cv.walk(
        getDirector(self),
        slotType,
        otext=otext,
        generic=generic,
        intFeatures=intFeatures,
        featureMeta=featureMeta,
        generateTf=True,
    )


def getDirector(self):
    """Factory for the director function.

    The `tf.convert.walker` relies on a corpus dependent `director` function
    that walks through the source data and spits out actions that
    produces the TF dataset.

    We collect all needed data, store it, and define a local director function
    that has access to this data.

    You can also include a copy of this file in the script that constructs the
    object. If you then tweak it, you can pass it to the XML() object constructor.

    Returns
    -------
    function
        The local director function that has been constructed.
    """

    SPLIT_REF = re.compile(r"[ :!]")

    PASS_THROUGH = set(
        """
        xml
        p
        milestone
        """.strip().split()
    )

    # CHECKING

    verbose = self.verbose
    xmlPath = self.xmlPath
    featureMeta = self.featureMeta
    transform = self.transform

    transformFunc = (
        (lambda x: BytesIO(x.encode("utf-8")))
        if transform is None
        else (lambda x: BytesIO(transform(x).encode("utf-8")))
    )

    parser = self.getParser()

    # WALKERS

    def walkNode(cv, cur, node):
        """Internal function to deal with a single element.

        Will be called recursively.

        Parameters
        ----------
        cv: object
            The convertor object, needed to issue actions.
        cur: dict
            Various pieces of data collected during walking
            and relevant for some next steps in the walk.
        node: object
            An lxml element node.
        """
        tag = etree.QName(node.tag).localname
        cur[NEST].append(tag)

        beforeChildren(cv, cur, node, tag)

        for child in node.iterchildren(tag=etree.Element):
            walkNode(cv, cur, child)

        afterChildren(cv, cur, node, tag)
        cur[NEST].pop()
        afterTag(cv, cur, node, tag)

    def beforeChildren(cv, cur, node, tag):
        """Actions before dealing with the element's children.

        Parameters
        ----------
        cv: object
            The convertor object, needed to issue actions.
        cur: dict
            Various pieces of data collected during walking
            and relevant for some next steps in the walk.
        node: object
            An lxml element node.
        tag: string
            The tag of the lxml node.
        """
        if tag in PASS_THROUGH:
            return

        atts = {etree.QName(k).localname: v for (k, v) in node.attrib.items()}

        if tag == "w":
            # atts["text"] = atts["unicode"]
            atts["text"] = node.text

            ref = atts["ref"]
            (bRef, chRef, vRef, wRef) = SPLIT_REF.split(ref)
            atts["book"] = bRef
            atts["chapter"] = chRef
            atts["verse"] = vRef
            atts["word_num"] = wRef
            thisChapterNum = atts["chapter"]
            thisVerseNum = atts["verse"]
            if thisChapterNum != cv.get("chapter", cur["chapter"]):
                if cur.get("verse", None) is not None:
                    cv.terminate(cur["verse"])
                if cur.get("chapter", None) is not None:
                    cv.terminate(cur["chapter"])

                curChapter = cv.node("chapter")
                cur["chapter"] = curChapter
                cv.feature(curChapter, chapter=thisChapterNum)

                curVerse = cv.node("verse")
                cur["verse"] = curVerse
                cv.feature(curVerse, verse=thisVerseNum)

            elif thisVerseNum != cv.get("verse", cur["verse"]):
                if cur.get("verse", None) is not None:
                    cv.terminate(cur["verse"])

                curVerse = cv.node("verse")
                cur["verse"] = curVerse
                cv.feature(curVerse, verse=thisVerseNum)

            key = f"B{cur['bookNum']:>03}-C{chRef:>03}-V{vRef:>03}-W{wRef:>04}"
            s = cv.slot(key=key)
            cv.feature(s, **atts)

        else:
            if tag == "book":
                cur["bookNum"] += 1
                atts["book_num"] = cur["bookNum"]
                atts["book_short"] = atts["id"]
                del atts["id"]

            elif tag == "sentence":
                cur["sentNum"] += 1
                atts["sent_num"] = cur["sentNum"]

            curNode = cv.node(tag)
            cur["elems"].append(curNode)
            if len(atts):
                cv.feature(curNode, **atts)

    def afterChildren(cv, cur, node, tag):
        """Node actions after dealing with the children, but before the end tag.

        Here we make sure that the newline elements will get their last slot
        having a newline at the end of their `after` feature.

        Parameters
        ----------
        cv: object
            The convertor object, needed to issue actions.
        cur: dict
            Various pieces of data collected during walking
            and relevant for some next steps in the walk.
        node: object
            An lxml element node.
        tag: string
            The tag of the lxml node.
        """
        if tag not in PASS_THROUGH:
            if tag == "book":
                cv.terminate(cur["verse"])
                cv.terminate(cur["chapter"])

            if tag != "w":
                curNode = cur["elems"].pop()

                cv.terminate(curNode)

    def afterTag(cv, cur, node, tag):
        """Node actions after dealing with the children and after the end tag.

        This is the place where we proces the `tail` of an lxml node: the
        text material after the element and before the next open/close
        tag of any element.

        Parameters
        ----------
        cv: object
            The convertor object, needed to issue actions.
        cur: dict
            Various pieces of data collected during walking
            and relevant for some next steps in the walk.
        node: object
            An lxml element node.
        tag: string
            The tag of the lxml node.
        """
        pass

    def director(cv):
        """Director function.

        Here we program a walk through the XML sources.
        At every step of the walk we fire some actions that build TF nodes
        and assign features for them.

        Because everything is rather dynamic, we generate fairly standard
        metadata for the features.

        Parameters
        ----------
        cv: object
            The convertor object, needed to issue actions.
        """
        cur = {}

        i = 0
        cur["bookNum"] = 0

        for (xmlFolder, xmlFiles) in self.getXML():
            for xmlFile in xmlFiles:
                i += 1
                console(f"\r{i:>4} {xmlFile:<50}", newline=False)

                with open(f"{xmlPath}/{xmlFolder}/{xmlFile}", encoding="utf8") as fh:
                    text = fh.read()
                    text = transformFunc(text)
                    tree = etree.parse(text, parser)
                    root = tree.getroot()
                    cur[NEST] = []
                    cur["elems"] = []
                    cur["chapter"] = None
                    cur["verse"] = None
                    cur["sentNum"] = 0
                    walkNode(cv, cur, root)

            console("")

        for fName in featureMeta:
            if not cv.occurs(fName):
                cv.meta(fName)
        for fName in cv.features():
            if fName not in featureMeta:
                cv.meta(
                    fName,
                    description=f"this is XML attribute {fName}",
                    valueType="str",
                )

        if verbose == 1:
            console("source reading done")
        return True

    return director
