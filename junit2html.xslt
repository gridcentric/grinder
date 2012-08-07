<xsl:stylesheet version="1.0"
        xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
    <xsl:template match="/">
        <html>
        <head>
        <script language="javascript" type="text/javascript">
        function show(name) {
            document.getElementById(name).style.display = 'block';
        }

        function hide(name) {
            document.getElementById(name).style.display = 'none';
        }

        function toggle(name) {
            if (document.getElementById(name).style.display == 'none')
                show(name)
            else
                hide(name)
        }
        </script>
        </head>
        <body>
            <xsl:for-each select="testsuite">
                <xsl:for-each select="testcase">
                    <a><xsl:attribute name="href">javascript:toggle(&quot;test<xsl:value-of select="position()"/>&quot;)</xsl:attribute>&gt;&gt;&gt;</a>
                    <xsl:text> </xsl:text>
                        <xsl:value-of select="@classname"/>.<xsl:value-of select="@name"/>
                        <xsl:if test="not(*)">
                            <font color="green">
                                - PASSED <br/>
                            </font>
                        </xsl:if>
                        <xsl:for-each select="skipped">
                            <font color="orange">
                                - SKIPPED <br/>
                            </font>
                        </xsl:for-each>
                        <xsl:for-each select="failure">
                            <font color="red">
                                - FAILED <br/>
                            </font>
                        </xsl:for-each>
                    <div style="display: none">
                        <xsl:attribute name="id">test<xsl:value-of select="position()"/></xsl:attribute>
                        <xsl:for-each select="failure">
                            <font color="red">
                                <pre><xsl:value-of select="."/></pre>
                            </font>
                        </xsl:for-each>
                        <xsl:for-each select="skipped">
                            <font color="orange">
                                <pre><xsl:value-of select="@message"/></pre>
                            </font>
                        </xsl:for-each>
                        <xsl:for-each select="system-out">
                            stdout <br/>
                            <pre><xsl:value-of select="."/></pre>
                        </xsl:for-each>
                        <xsl:for-each select="system-err">
                            stderr <br/>
                            <pre><xsl:value-of select="."/></pre>
                        </xsl:for-each>
                    </div>
                </xsl:for-each>
            </xsl:for-each>
        </body>
        </html>
    </xsl:template>
</xsl:stylesheet>
