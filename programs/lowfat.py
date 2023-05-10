import re
from lxml import etree
from io import BytesIO

from tf.core.helpers import console
from tf.core.files import initTree, unexpanduser as ux

from tf.convert.helpers import NEST

demoMode = False


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
        "sectionFeatures": "book,chapter,verse",
    }
    intFeatures = {
        "appositioncontainer",
        "articular",
        "chapter",
        "discontinuous",
        "nodeId",
        "num",
        "strong",
        "verse",
    }
    monoAtts = {"appositioncontainer", "articular", "discontinuous"}
    featureMeta = (
        ("after", "material after the end of the word"),
        ("appositioncontainer", "1 if it is an apposition container"),
        ("articular", "1 if the wg has an article"),
        ("book", "book name (abbreviated), from ref attribute in xml"),
        ("case", "grammatical case"),
        ("chapter", "chapter number, from ref attribute in xml"),
        ("class", "morphological class (on w); syntactical class (on wg)"),
        ("clauseType", "clause type"),
        ("cltype", "clause type"),
        ("crule", "clause rule (from xml attribute Rule)"),
        ("degree", "grammatical degree"),
        ("discontinuous", "1 if the word is out of sequence in the xml"),
        ("domain", "domain"),
        ("frame", "frame"),
        ("gender", "grammatical gender"),
        ("gloss", "short translation"),
        ("id", "xml id"),
        ("junction", "type of junction"),
        ("lang", "language the text is in"),
        ("lemma", "lexical lemma"),
        ("ln", "ln"),
        ("mood", "verbal mood"),
        ("morph", "morphological code"),
        ("nodeId", "node id (as in the XML source data"),
        ("normalized", "lemma normalized"),
        (
            "num",
            (
                "generated number (not in xml): "
                "book: (Matthew=1, Mark=2, ..., Revelation=27); "
                "sentence: numbered per chapter; "
                "word: numbered per verse."
            ),
        ),
        ("number", "grammatical number"),
        ("note", "annotation of linguistic nature"),
        ("person", "grammatical person"),
        ("ref", "biblical reference with word counting"),
        ("referent", "number of referent"),
        ("strong", "strong number"),
        ("subjref", "number of subject referent"),
        ("role", "role"),
        ("rule", "syntactical rule"),
        ("text", "the text of a word"),
        ("tense", "verbal tense"),
        ("type", "morphological type (on w), syntactical type (on wg)"),
        ("unicode", "word in unicode characters plus material after it"),
        ("verse", "verse number, from ref attribute in xml"),
        ("voice", "verbal voice"),
    )
    featureMeta = {k: dict(description=v) for (k, v) in featureMeta}

    self.intFeatures = intFeatures
    self.featureMeta = featureMeta
    self.monoAtts = monoAtts

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
    renameAtts = self.renameAtts
    monoAtts = self.monoAtts

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
        atts = {renameAtts.get(k, k): v for (k, v) in atts.items()}
        for m in monoAtts:
            if atts.get(m, None) == "true":
                atts[m] = 1

        if tag == "w":
            # atts["text"] = atts["unicode"]
            atts["text"] = node.text

            ref = atts["ref"]
            (bRef, chRef, vRef, wRef) = SPLIT_REF.split(ref)
            atts["book"] = bRef
            atts["chapter"] = chRef
            atts["verse"] = vRef
            atts["num"] = wRef
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

            if demoMode:
                if cur["sentNum"] == 1:
                    key = None

            s = cv.slot(key=key)
            cv.feature(s, **atts)

        else:
            if tag == "book":
                cur["bookNum"] += 1
                atts["num"] = cur["bookNum"]
                atts["book"] = atts["id"]
                del atts["id"]

            elif tag == "sentence":
                cur["sentNum"] += 1
                atts["num"] = cur["sentNum"]

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
