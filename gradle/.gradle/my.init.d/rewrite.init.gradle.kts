import org.openrewrite.gradle.RewriteExtension
import org.openrewrite.gradle.RewritePlugin
import java.io.File

// Lives outside ~/.gradle/init.d, which is the only directory Gradle auto-scans — this script
// only runs when passed explicitly. Extension must stay .gradle.kts (Gradle picks Kotlin vs Groovy
// DSL from the file extension even for an explicit --init-script path).
//   ./gradlew rewriteRun    --init-script ~/.gradle/my.init.d/rewrite.init.gradle.kts
//   ./gradlew rewriteDryRun --init-script ~/.gradle/my.init.d/rewrite.init.gradle.kts
//   ./gradlew :rewriteRun --init-script ~/.gradle/my.init.d/rewrite.init.gradle.kts --no-parallel --no-configuration-cache

initscript {
    repositories {
        gradlePluginPortal()
        mavenCentral()
    }
    dependencies {
        classpath("org.openrewrite:plugin:7.39.0")
    }
}

gradle.rootProject {
    pluginManager.apply(RewritePlugin::class.java)

    dependencies {
        "rewrite"("org.openrewrite:rewrite-java:8.56.1")
    }

    extensions.configure<RewriteExtension> {
        configFile = File(gradle.gradleUserHomeDir, "rewrite/mockito-static-imports.yml")
        activeRecipe("com.yourcompany.MockitoStaticImports")
    }
}
